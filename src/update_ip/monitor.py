import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Optional, Tuple

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from update_ip.bark_notifier import BarkNotifier
from update_ip.config import Settings
from update_ip.ip_checker import IPChecker
from update_ip.state_manager import StateManager

console = Console()


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_time=True, show_path=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger("update_ip.monitor")


class IPMonitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.checker = IPChecker(
            providers=settings.ip_providers,
            timeout=settings.request_timeout,
            max_retries_per_provider=settings.max_retries_per_provider,
            ip_version=settings.ip_version,
        )
        self.notifier = BarkNotifier(
            bark_key=settings.bark_key,
            bark_server=settings.bark_server,
            default_group=settings.bark_group,
            default_icon=settings.bark_icon,
            default_sound=settings.bark_sound,
            default_level=settings.bark_level,
            timeout=settings.request_timeout,
        )
        self.state = StateManager(settings.cache_file)
        self._stop_event = asyncio.Event()

    async def _notify_change(self, old_ip: str, new_ip: str, provider: str, now_str: str) -> bool:
        """Return True only when a required notification was delivered or no notifier is configured."""
        if not self.notifier.is_configured():
            return True

        success, message = await self.notifier.send(
            "🚨 公网 IP 发生变更",
            f"原 IP: {old_ip}\n新 IP: {new_ip}\n接口: {provider}\n时间: {now_str}",
        )
        if not success:
            logger.error(
                "[red]IP changed but Bark delivery failed.[/red] State was not advanced; "
                "the notification will be retried on the next check. Reason: %s",
                message,
            )
        return success

    async def check_once(self, is_startup: bool = False) -> Tuple[bool, str, Optional[str]]:
        current_ip, provider = await self.checker.get_current_ip()
        last_ip = self.state.get_last_ip()
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

        ip_changed = last_ip is not None and current_ip != last_ip
        is_first_run = last_ip is None

        if is_first_run:
            logger.info("[green]First run initialized.[/green] Current IP: [bold cyan]%s[/bold cyan] (via %s)", current_ip, provider)
            self.state.save_ip(current_ip, provider=provider)
            if is_startup and self.settings.notify_on_start and self.notifier.is_configured():
                await self.notifier.send(
                    "🟢 IP 监控已启动",
                    f"当前公网 IP: {current_ip}\n接口: {provider}\n检查间隔: {self.settings.check_interval}s\n时间: {now_str}",
                )
            return False, current_ip, None

        if ip_changed:
            logger.warning(
                "[bold red]🚨 IP Changed![/bold red] Old: [red]%s[/red] -> New: "
                "[bold green]%s[/bold green] (via %s)",
                last_ip,
                current_ip,
                provider,
            )
            if await self._notify_change(last_ip, current_ip, provider, now_str):
                self.state.save_ip(current_ip, provider=provider)
            return True, current_ip, last_ip

        if is_startup:
            logger.info("IP Monitor started. Current IP: [bold cyan]%s[/bold cyan] (matches cached IP)", current_ip)
            if self.settings.notify_on_start and self.notifier.is_configured():
                await self.notifier.send(
                    "🟢 IP 监控已启动",
                    f"当前公网 IP: {current_ip}\n状态: 未变动\n检查间隔: {self.settings.check_interval}s\n时间: {now_str}",
                )
        else:
            logger.debug("IP unchanged: %s", current_ip)
        return False, current_ip, last_ip

    async def run_forever(self) -> None:
        logger.info(
            "[bold green]Starting IP monitor daemon[/bold green] (Interval: %ss, IPv%s, Bark: %s)",
            self.settings.check_interval,
            self.settings.ip_version,
            "Configured" if self.notifier.is_configured() else "Not configured",
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: self._stop_event.set())
            except NotImplementedError:
                pass

        try:
            await self.check_once(is_startup=True)
        except Exception as e:
            logger.error("[red]Initial IP check failed:[/red] %s. Will retry.", e)

        while not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.check_interval)
                    if self._stop_event.is_set():
                        break
                except asyncio.TimeoutError:
                    pass

                await self.check_once(is_startup=False)
            except Exception as e:
                logger.error("[yellow]Error during IP check loop:[/yellow] %s", e)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=min(self.settings.check_interval, 15))
                except asyncio.TimeoutError:
                    pass

        logger.info("[bold yellow]IP Monitor daemon stopped gracefully.[/bold yellow]")

    async def test(self) -> None:
        console.print("\n[bold cyan]=== 🔍 Running IP Monitor Diagnostic Test ===[/bold cyan]\n")
        console.print("[bold]1. Testing IP Providers:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Provider Endpoint", style="dim", width=42)
        table.add_column("Status", width=12)
        table.add_column("Detected IP / Error", width=40)

        results = await self.checker.test_all_providers()
        for result in results:
            if result["success"]:
                table.add_row(result["provider"], "[green]✓ Success[/green]", f"[cyan]{result['ip']}[/cyan]")
            else:
                table.add_row(result["provider"], "[red]✗ Failed[/red]", f"[red]{result['error'][:38]}[/red]")
        console.print(table)

        console.print("\n[bold]2. Testing Bark Notification:[/bold]")
        if not self.notifier.is_configured():
            console.print("[yellow]⚠ Bark Key is not configured. Bark notification skipped.[/yellow]")
        else:
            now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            success, msg = await self.notifier.send(
                "🔔 Bark 连接测试成功",
                f"这是一条来自 IP 变动监控脚本的测试通知。\n当前时间: {now_str}",
            )
            console.print(f"[{'green' if success else 'red'}]{msg}[/]")

    def show_status(self) -> None:
        last_ip = self.state.get_last_ip()
        data = self.state.load()
        history = data.get("history", [])
        console.print(f"\n[bold]Current Cached IP:[/bold] [bold cyan]{last_ip or 'None'}[/bold cyan]")
        console.print(f"[bold]Last Updated:[/bold] {data.get('last_updated', 'N/A')}")
        console.print(f"[bold]Total Recorded Changes:[/bold] {len(history)}\n")

        if history:
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Time", width=25)
            table.add_column("Previous IP", width=18)
            table.add_column("New IP", style="green", width=18)
            table.add_column("Provider", style="dim")
            for item in reversed(history[-15:]):
                table.add_row(
                    item.get("timestamp", "N/A"),
                    str(item.get("previous_ip") or "Initial"),
                    str(item.get("ip")),
                    str(item.get("provider") or "N/A"),
                )
            console.print(table)
