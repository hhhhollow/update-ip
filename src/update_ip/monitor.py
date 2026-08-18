import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from update_ip.bark_notifier import BarkNotifier
from update_ip.config import Settings
from update_ip.ip_checker import IPChecker
from update_ip.state_manager import StateManager

console = Console()

CHANNEL_LABELS = {
    "domestic": "国内公网 IP",
    "foreign": "国外出口 IP",
}


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
        self.domestic_checker = IPChecker(
            providers=settings.domestic_ip_providers,
            timeout=settings.request_timeout,
            max_retries_per_provider=settings.max_retries_per_provider,
            ip_version=settings.ip_version,
        )
        self.foreign_checker = IPChecker(
            providers=settings.ip_providers,
            timeout=settings.request_timeout,
            max_retries_per_provider=settings.max_retries_per_provider,
            ip_version=settings.ip_version,
        )
        # Compatibility alias for callers that previously accessed monitor.checker.
        self.checker = self.foreign_checker
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
        self.last_results: Dict[str, Dict[str, Any]] = {}

    async def _notify_change(
        self,
        scope: str,
        old_ip: str,
        new_ip: str,
        provider: str,
        now_str: str,
    ) -> bool:
        """Return True only when a required notification was delivered or no notifier is configured."""
        if not self.notifier.is_configured():
            return True

        label = CHANNEL_LABELS[scope]
        success, message = await self.notifier.send(
            f"🚨 {label} 发生变更",
            f"原 IP: {old_ip}\n新 IP: {new_ip}\n接口: {provider}\n时间: {now_str}",
        )
        if not success:
            logger.error(
                "[red]%s changed but Bark delivery failed.[/red] State was not advanced; "
                "the notification will be retried on the next check. Reason: %s",
                label,
                message,
            )
        return success

    async def _fetch_channels(
        self,
    ) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, BaseException]]:
        scopes = ("domestic", "foreign")
        responses = await asyncio.gather(
            self.domestic_checker.get_current_ip(),
            self.foreign_checker.get_current_ip(),
            return_exceptions=True,
        )

        successes: Dict[str, Tuple[str, str]] = {}
        errors: Dict[str, BaseException] = {}
        for scope, response in zip(scopes, responses):
            if isinstance(response, BaseException):
                errors[scope] = response
                logger.error(
                    "[yellow]%s check failed:[/yellow] %s",
                    CHANNEL_LABELS[scope],
                    response,
                )
            else:
                successes[scope] = response

        if not successes:
            details = "; ".join(
                f"{CHANNEL_LABELS[scope]}: {error}" for scope, error in errors.items()
            )
            raise RuntimeError(f"Both domestic and foreign IP checks failed: {details}")

        return successes, errors

    async def _process_channel(
        self,
        scope: str,
        current_ip: str,
        provider: str,
        now_str: str,
        is_startup: bool,
    ) -> Dict[str, Any]:
        label = CHANNEL_LABELS[scope]
        last_ip = self.state.get_last_ip(scope)
        is_first_run = last_ip is None
        ip_changed = last_ip is not None and current_ip != last_ip
        state_advanced = False

        if is_first_run:
            logger.info(
                "[green]First run initialized for %s.[/green] Current IP: "
                "[bold cyan]%s[/bold cyan] (via %s)",
                label,
                current_ip,
                provider,
            )
            self.state.save_ip(current_ip, provider=provider, scope=scope)
            state_advanced = True
        elif ip_changed:
            logger.warning(
                "[bold red]🚨 %s Changed![/bold red] Old: [red]%s[/red] -> New: "
                "[bold green]%s[/bold green] (via %s)",
                label,
                last_ip,
                current_ip,
                provider,
            )
            if await self._notify_change(scope, last_ip, current_ip, provider, now_str):
                self.state.save_ip(current_ip, provider=provider, scope=scope)
                state_advanced = True
        elif is_startup:
            logger.info(
                "%s monitor started. Current IP: [bold cyan]%s[/bold cyan] (matches cached IP)",
                label,
                current_ip,
            )
        else:
            logger.debug("%s unchanged: %s", label, current_ip)

        return {
            "ip": current_ip,
            "provider": provider,
            "previous_ip": last_ip,
            "changed": ip_changed,
            "initialized": is_first_run,
            "state_advanced": state_advanced,
            "error": None,
        }

    async def check_once(self, is_startup: bool = False) -> Dict[str, Dict[str, Any]]:
        fetched, errors = await self._fetch_channels()
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        results: Dict[str, Dict[str, Any]] = {}

        for scope in ("domestic", "foreign"):
            if scope in fetched:
                current_ip, provider = fetched[scope]
                results[scope] = await self._process_channel(
                    scope,
                    current_ip,
                    provider,
                    now_str,
                    is_startup,
                )
            else:
                results[scope] = {
                    "ip": None,
                    "provider": None,
                    "previous_ip": self.state.get_last_ip(scope),
                    "changed": False,
                    "initialized": False,
                    "state_advanced": False,
                    "error": str(errors[scope]),
                }

        self.last_results = results

        if is_startup and self.settings.notify_on_start and self.notifier.is_configured():
            lines = []
            for scope in ("domestic", "foreign"):
                result = results[scope]
                label = CHANNEL_LABELS[scope]
                if result["error"]:
                    lines.append(f"{label}: 检查失败")
                else:
                    lines.append(f"{label}: {result['ip']}")
            lines.extend([
                f"检查间隔: {self.settings.check_interval}s",
                f"时间: {now_str}",
            ])
            await self.notifier.send("🟢 IP 监控已启动", "\n".join(lines))

        return results

    async def run_forever(self) -> None:
        logger.info(
            "[bold green]Starting dual IP monitor daemon[/bold green] "
            "(Interval: %ss, IPv%s, Bark: %s)",
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
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=min(self.settings.check_interval, 15),
                    )
                except asyncio.TimeoutError:
                    pass

        logger.info("[bold yellow]IP Monitor daemon stopped gracefully.[/bold yellow]")

    async def _print_provider_diagnostics(self, title: str, checker: IPChecker) -> None:
        console.print(f"\n[bold]{title}[/bold]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Provider Endpoint", style="dim", width=42)
        table.add_column("Status", width=12)
        table.add_column("Detected IP / Error", width=40)

        results = await checker.test_all_providers()
        for result in results:
            if result["success"]:
                table.add_row(
                    result["provider"],
                    "[green]✓ Success[/green]",
                    f"[cyan]{result['ip']}[/cyan]",
                )
            else:
                table.add_row(
                    result["provider"],
                    "[red]✗ Failed[/red]",
                    f"[red]{result['error'][:38]}[/red]",
                )
        console.print(table)

    async def test(self) -> None:
        console.print("\n[bold cyan]=== 🔍 Running IP Monitor Diagnostic Test ===[/bold cyan]")
        await self._print_provider_diagnostics(
            "1. Testing Domestic IP Providers:",
            self.domestic_checker,
        )
        await self._print_provider_diagnostics(
            "2. Testing Foreign IP Providers:",
            self.foreign_checker,
        )

        console.print("\n[bold]3. Testing Bark Notification:[/bold]")
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
        domestic_ip = self.state.get_last_ip("domestic")
        foreign_ip = self.state.get_last_ip("foreign")
        data = self.state.load()
        history = data.get("history", [])

        console.print(
            f"\n[bold]Cached Domestic IP:[/bold] "
            f"[bold cyan]{domestic_ip or 'None'}[/bold cyan]"
        )
        console.print(
            f"[bold]Cached Foreign IP:[/bold] "
            f"[bold cyan]{foreign_ip or 'None'}[/bold cyan]"
        )
        console.print(f"[bold]Last Updated:[/bold] {data.get('last_updated', 'N/A')}")
        console.print(f"[bold]Total Recorded Changes:[/bold] {len(history)}\n")

        if history:
            table = Table(show_header=True, header_style="bold blue")
            table.add_column("Time", width=25)
            table.add_column("Channel", width=10)
            table.add_column("Previous IP", width=18)
            table.add_column("New IP", style="green", width=18)
            table.add_column("Provider", style="dim")
            for item in reversed(history[-15:]):
                scope = str(item.get("scope") or "foreign")
                table.add_row(
                    item.get("timestamp", "N/A"),
                    "Domestic" if scope == "domestic" else "Foreign",
                    str(item.get("previous_ip") or "Initial"),
                    str(item.get("ip")),
                    str(item.get("provider") or "N/A"),
                )
            console.print(table)
