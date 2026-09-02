import asyncio
import logging
import signal
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from update_ip.bark_notifier import BarkNotifier
from update_ip.config import Settings
from update_ip.ip_checker import IPChecker
from update_ip.state_manager import StateManager

console = Console()
logger = logging.getLogger("update_ip.monitor")

SCOPES = ("domestic", "foreign")
CHANNEL_LABELS = {
    "domestic": "国内公网 IP",
    "foreign": "国外出口 IP",
}
FAILURE_ALERT_THRESHOLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, show_time=True, show_path=False)],
    )
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class IPMonitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        checker_options = {
            "timeout": settings.request_timeout,
            "max_retries_per_provider": settings.max_retries_per_provider,
            "ip_version": settings.ip_version,
        }
        self.checkers = {
            "domestic": IPChecker(providers=settings.domestic_ip_providers, **checker_options),
            "foreign": IPChecker(providers=settings.ip_providers, **checker_options),
        }
        self.domestic_checker = self.checkers["domestic"]
        self.foreign_checker = self.checkers["foreign"]
        self.checker = self.foreign_checker  # backwards compatibility
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
        self.last_results: dict[str, dict[str, Any]] = {}

    async def _notify(self, title: str, body: str, failure_message: str) -> bool:
        if not self.notifier.is_configured():
            return False
        success, message = await self.notifier.send(title, body)
        if not success:
            logger.error("[red]%s[/red] Reason: %s", failure_message, message)
        return success

    async def _handle_check_failure(self, scope: str, error: BaseException, now: str) -> None:
        health = self.state.record_failure(scope, str(error))
        count = health["consecutive_failures"]
        label = CHANNEL_LABELS[scope]
        logger.warning("%s consecutive check failures: %s", label, count)

        if count < FAILURE_ALERT_THRESHOLD or health["alert_active"]:
            return
        if not self.notifier.is_configured():
            logger.warning("%s reached the failure alert threshold, but Bark is not configured.", label)
            return

        if await self._notify(
            f"⚠️ {label} 连续查询失败",
            f"已连续失败: {count} 次\n最近错误: {error}\n时间: {now}",
            f"{label} failure alert delivery failed. Will retry on the next failed check.",
        ):
            self.state.mark_failure_alerted(scope)

    async def _handle_check_success(
        self,
        scope: str,
        current_ip: str,
        provider: str,
        now: str,
    ) -> None:
        health = self.state.record_success(scope)
        if not health["alert_active"]:
            return

        count = health["outage_failure_count"] or health.get("previous_failures", 0)
        label = CHANNEL_LABELS[scope]
        if await self._notify(
            f"✅ {label} 查询已恢复",
            f"此前连续失败: {count} 次\n当前 IP: {current_ip}\n接口: {provider}\n时间: {now}",
            f"{label} recovery notification delivery failed. Will retry on the next successful check.",
        ):
            self.state.clear_failure_alert(scope)

    async def _fetch_channels(
        self,
    ) -> tuple[dict[str, tuple[str, str]], dict[str, BaseException]]:
        responses = await asyncio.gather(
            *(self.checkers[scope].get_current_ip() for scope in SCOPES),
            return_exceptions=True,
        )
        successes: dict[str, tuple[str, str]] = {}
        errors: dict[str, BaseException] = {}

        for scope, response in zip(SCOPES, responses):
            if isinstance(response, BaseException):
                errors[scope] = response
                logger.error("[yellow]%s check failed:[/yellow] %s", CHANNEL_LABELS[scope], response)
            else:
                successes[scope] = response
        return successes, errors

    async def _process_channel(
        self,
        scope: str,
        current_ip: str,
        provider: str,
        now: str,
        is_startup: bool,
    ) -> dict[str, Any]:
        label = CHANNEL_LABELS[scope]
        last_ip = self.state.get_last_ip(scope)
        initialized = last_ip is None
        changed = last_ip is not None and current_ip != last_ip
        state_advanced = False

        if initialized:
            logger.info(
                "[green]First run initialized for %s.[/green] Current IP: [bold cyan]%s[/bold cyan] (via %s)",
                label,
                current_ip,
                provider,
            )
            self.state.save_ip(current_ip, provider=provider, scope=scope)
            state_advanced = True
        elif changed:
            logger.warning(
                "[bold red]🚨 %s Changed![/bold red] Old: [red]%s[/red] -> New: [bold green]%s[/bold green] (via %s)",
                label,
                last_ip,
                current_ip,
                provider,
            )
            delivered = not self.notifier.is_configured() or await self._notify(
                f"🚨 {label} 发生变更",
                f"原 IP: {last_ip}\n新 IP: {current_ip}\n接口: {provider}\n时间: {now}",
                f"{label} changed but Bark delivery failed. State was not advanced; the notification will be retried on the next check.",
            )
            if delivered:
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
            "changed": changed,
            "initialized": initialized,
            "state_advanced": state_advanced,
            "error": None,
        }

    async def check_once(self, is_startup: bool = False) -> dict[str, dict[str, Any]]:
        fetched, errors = await self._fetch_channels()
        now = _now()
        results: dict[str, dict[str, Any]] = {}

        for scope in SCOPES:
            if scope in fetched:
                current_ip, provider = fetched[scope]
                await self._handle_check_success(scope, current_ip, provider, now)
                results[scope] = await self._process_channel(
                    scope, current_ip, provider, now, is_startup
                )
                continue

            error = errors[scope]
            await self._handle_check_failure(scope, error, now)
            results[scope] = {
                "ip": None,
                "provider": None,
                "previous_ip": self.state.get_last_ip(scope),
                "changed": False,
                "initialized": False,
                "state_advanced": False,
                "error": str(error),
            }

        self.last_results = results
        if is_startup and self.settings.notify_on_start and self.notifier.is_configured():
            lines = [
                f"{CHANNEL_LABELS[scope]}: "
                + ("检查失败" if results[scope]["error"] else str(results[scope]["ip"]))
                for scope in SCOPES
            ]
            lines += [f"检查间隔: {self.settings.check_interval}s", f"时间: {now}"]
            await self.notifier.send("🟢 IP 监控已启动", "\n".join(lines))

        return results

    async def run_forever(self) -> None:
        logger.info(
            "[bold green]Starting dual IP monitor daemon[/bold green] (Interval: %ss, IPv%s, Bark: %s)",
            self.settings.check_interval,
            self.settings.ip_version,
            "Configured" if self.notifier.is_configured() else "Not configured",
        )
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                pass

        try:
            await self.check_once(is_startup=True)
        except Exception as exc:
            logger.error("[red]Initial IP check failed:[/red] %s. Will retry.", exc)

        while not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.settings.check_interval
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                await self.check_once()
            except Exception as exc:
                logger.error("[yellow]Error during IP check loop:[/yellow] %s", exc)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=min(self.settings.check_interval, 15)
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

        for result in await checker.test_all_providers():
            if result["success"]:
                table.add_row(result["provider"], "[green]✓ Success[/green]", f"[cyan]{result['ip']}[/cyan]")
            else:
                table.add_row(result["provider"], "[red]✗ Failed[/red]", f"[red]{result['error'][:38]}[/red]")
        console.print(table)

    async def test(self) -> None:
        console.print("\n[bold cyan]=== 🔍 Running IP Monitor Diagnostic Test ===[/bold cyan]")
        for index, scope in enumerate(SCOPES, 1):
            await self._print_provider_diagnostics(
                f"{index}. Testing {scope.title()} IP Providers:", self.checkers[scope]
            )

        console.print("\n[bold]3. Testing Bark Notification:[/bold]")
        if not self.notifier.is_configured():
            console.print("[yellow]⚠ Bark Key is not configured. Bark notification skipped.[/yellow]")
            return
        success, message = await self.notifier.send(
            "🔔 Bark 连接测试成功",
            f"这是一条来自 IP 变动监控脚本的测试通知。\n当前时间: {_now()}",
        )
        console.print(f"[{'green' if success else 'red'}]{message}[/]")

    def show_status(self) -> None:
        data = self.state.load()
        for scope in SCOPES:
            console.print(
                f"[bold]Cached {scope.title()} IP:[/bold] "
                f"[bold cyan]{self.state.get_last_ip(scope) or 'None'}[/bold cyan]"
            )
        history = data.get("history", [])
        console.print(f"[bold]Last Updated:[/bold] {data.get('last_updated', 'N/A')}")
        console.print(f"[bold]Total Recorded Changes:[/bold] {len(history)}\n")

        if not history:
            return
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
                scope.title(),
                str(item.get("previous_ip") or "Initial"),
                str(item.get("ip")),
                str(item.get("provider") or "N/A"),
            )
        console.print(table)
