import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
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
        handlers=[
            RichHandler(
                rich_tracebacks=True,
                console=console,
                show_time=True,
                show_path=False,
            )
        ],
    )
    # Silence noisy third-party loggers
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

    async def check_once(self, is_startup: bool = False) -> Tuple[bool, str, Optional[str]]:
        """
        Perform a single check of the public IP.
        Returns:
            Tuple[bool, str, Optional[str]]: (ip_changed, current_ip, previous_ip)
        """
        current_ip, provider = await self.checker.get_current_ip()
        last_ip = self.state.get_last_ip()
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

        ip_changed = (last_ip is not None and current_ip != last_ip)
        is_first_run = (last_ip is None)

        if is_startup:
            if is_first_run:
                logger.info(f"[green]First run initialized.[/green] Current IP: [bold cyan]{current_ip}[/bold cyan] (via {provider})")
                self.state.save_ip(current_ip, provider=provider)
                if self.settings.notify_on_start and self.notifier.is_configured():
                    title = "🟢 IP 监控已启动"
                    body = f"当前公网 IP: {current_ip}\n接口: {provider}\n检查间隔: {self.settings.check_interval}s\n时间: {now_str}"
                    await self.notifier.send(title, body)
                return True, current_ip, None

            elif ip_changed:
                logger.warning(f"[yellow]IP changed during offline period![/yellow] Previous: {last_ip} -> Current: [bold cyan]{current_ip}[/bold cyan]")
                self.state.save_ip(current_ip, provider=provider)
                if self.notifier.is_configured():
                    title = "🚨 公网 IP 发生变更"
                    body = f"原 IP: {last_ip}\n新 IP: {current_ip}\n接口: {provider}\n时间: {now_str}"
                    await self.notifier.send(title, body)
                return True, current_ip, last_ip

            else:
                logger.info(f"IP Monitor started. Current IP: [bold cyan]{current_ip}[/bold cyan] (matches cached IP)")
                if self.settings.notify_on_start and self.notifier.is_configured():
                    title = "🟢 IP 监控已启动"
                    body = f"当前公网 IP: {current_ip}\n状态: 未变动\n检查间隔: {self.settings.check_interval}s\n时间: {now_str}"
                    await self.notifier.send(title, body)
                return False, current_ip, last_ip

        # Regular periodic check
        if ip_changed:
            logger.warning(f"[bold red]🚨 IP Changed![/bold red] Old: [red]{last_ip}[/red] -> New: [bold green]{current_ip}[/bold green] (via {provider})")
            self.state.save_ip(current_ip, provider=provider)
            if self.notifier.is_configured():
                title = "🚨 公网 IP 发生变更"
                body = f"原 IP: {last_ip}\n新 IP: {current_ip}\n接口: {provider}\n时间: {now_str}"
                await self.notifier.send(title, body)
            return True, current_ip, last_ip
        elif is_first_run:
            logger.info(f"Saving initial IP: [bold cyan]{current_ip}[/bold cyan]")
            self.state.save_ip(current_ip, provider=provider)
            return True, current_ip, None
        else:
            logger.debug(f"IP unchanged: {current_ip}")
            return False, current_ip, last_ip

    async def run_forever(self) -> None:
        """Continuous monitoring loop with graceful shutdown and error recovery."""
        logger.info(
            f"[bold green]Starting IP monitor daemon[/bold green] (Interval: {self.settings.check_interval}s, "
            f"Bark: {'Configured' if self.notifier.is_configured() else '[yellow]Not configured[/yellow]'})"
        )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: self._stop_event.set())
            except NotImplementedError:
                # Windows fallback
                pass

        # Startup check
        try:
            await self.check_once(is_startup=True)
        except Exception as e:
            logger.error(f"[red]Initial IP check failed:[/red] {e}. Will retry in {self.settings.check_interval}s.")

        # Monitoring loop
        while not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.check_interval)
                    if self._stop_event.is_set():
                        break
                except asyncio.TimeoutError:
                    pass

                if self._stop_event.is_set():
                    break

                logger.debug("Checking for IP changes...")
                await self.check_once(is_startup=False)

            except Exception as e:
                logger.error(f"[yellow]Error during IP check loop:[/yellow] {e}")
                # Wait briefly before continuing to avoid tight error loop
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=min(self.settings.check_interval, 15))
                except asyncio.TimeoutError:
                    pass

        logger.info("[bold yellow]IP Monitor daemon stopped gracefully.[/bold yellow]")

    async def test(self) -> None:
        """Run connectivity and provider diagnostics, plus Bark test push."""
        console.print("\n[bold cyan]=== 🔍 Running IP Monitor Diagnostic Test ===[/bold cyan]\n")

        # 1. Test all IP Providers
        console.print("[bold]1. Testing IP Providers:[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Provider Endpoint", style="dim", width=42)
        table.add_column("Status", width=12)
        table.add_column("Detected IP / Error", width=40)

        results = await self.checker.test_all_providers()
        for r in results:
            if r["success"]:
                table.add_row(r["provider"], "[green]✓ Success[/green]", f"[cyan]{r['ip']}[/cyan]")
            else:
                table.add_row(r["provider"], "[red]✗ Failed[/red]", f"[red]{r['error'][:38]}[/red]")

        console.print(table)

        # 2. Test Bark Notification
        console.print("\n[bold]2. Testing Bark Notification:[/bold]")
        if not self.notifier.is_configured():
            console.print("[yellow]⚠ Bark Key is not configured in .env or arguments. Bark notification skipped.[/yellow]")
            console.print("To configure, edit `.env` or pass `--key YOUR_BARK_KEY`.\n")
        else:
            console.print(f"Sending test notification to Bark server [cyan]{self.settings.bark_server}[/cyan]...")
            now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            success, msg = await self.notifier.send(
                title="🔔 Bark 连接测试成功",
                body=f"这是一条来自 IP 变动监控脚本的测试通知。\n当前时间: {now_str}",
            )
            if success:
                console.print(f"[bold green]✓ Bark notification sent successfully![/bold green] Response: {msg}")
            else:
                console.print(f"[bold red]✗ Bark notification failed![/bold red] Reason: {msg}")

        console.print("\n[bold cyan]=== Diagnostic Test Complete ===[/bold cyan]\n")

    def show_status(self) -> None:
        """Display cached state and historical changes."""
        console.print("\n[bold cyan]=== 📊 IP Monitor Status & History ===[/bold cyan]\n")
        last_ip = self.state.get_last_ip()
        data = self.state.load()
        last_updated = data.get("last_updated", "N/A")
        history = data.get("history", [])

        console.print(f"[bold]Current Cached IP:[/bold] [bold cyan]{last_ip or 'None'}[/bold cyan]")
        console.print(f"[bold]Last Updated:[/bold] {last_updated}")
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
        console.print()
