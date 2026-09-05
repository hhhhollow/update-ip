import plistlib
import shutil
import subprocess
from pathlib import Path

from rich.console import Console

console = Console()

DEFAULT_LAUNCHD_INTERVAL = 300
SERVICE_LABEL = "com.update-ip.monitor"


def default_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def generate_plist(
    target_path: Path | None = None,
    interval_seconds: int = DEFAULT_LAUNCHD_INTERVAL,
    monitor_args: list[str] | None = None,
) -> Path:
    if interval_seconds < 1:
        raise ValueError("launchd interval must be at least 1 second")

    working_dir = Path.cwd().resolve()
    log_dir = working_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    uv_path = shutil.which("uv") or "uv"

    content = {
        "Label": SERVICE_LABEL,
        "WorkingDirectory": str(working_dir),
        "ProgramArguments": [
            uv_path, "run", "--directory", str(working_dir), "update-ip", "--once",
            *(monitor_args or []),
        ],
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "StandardOutPath": str(log_dir / "stdout.log"),
        "StandardErrorPath": str(log_dir / "stderr.log"),
    }

    if target_path is None:
        target_path = default_plist_path()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(plistlib.dumps(content))
    return target_path


def start_service(
    interval_seconds: int = DEFAULT_LAUNCHD_INTERVAL,
    monitor_args: list[str] | None = None,
) -> Path:
    plist_path = generate_plist(interval_seconds=interval_seconds, monitor_args=monitor_args)
    subprocess.run(
        ["launchctl", "unload", "-w", str(plist_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    result = subprocess.run(
        ["launchctl", "load", "-w", str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "launchctl load failed"
        raise RuntimeError(message)
    console.print(f"[green]✓ {SERVICE_LABEL} started (every {interval_seconds} seconds)[/green]")
    return plist_path


def stop_service() -> bool:
    plist_path = default_plist_path()
    if not plist_path.exists():
        console.print(f"[yellow]• {SERVICE_LABEL} is already stopped[/yellow]")
        return False

    result = subprocess.run(
        ["launchctl", "unload", "-w", str(plist_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        if "Could not find specified service" not in message:
            raise RuntimeError(message or "launchctl unload failed")
    console.print(f"[green]✓ {SERVICE_LABEL} stopped[/green]")
    return True


def service_is_running() -> bool:
    result = subprocess.run(
        ["launchctl", "list", SERVICE_LABEL],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def print_service_status() -> bool:
    running = service_is_running()
    if running:
        console.print(f"[green]● {SERVICE_LABEL}: enabled[/green]")
    else:
        console.print(f"[yellow]○ {SERVICE_LABEL}: disabled[/yellow]")
    return running


def print_service_instructions(
    plist_path: Path,
    interval_seconds: int = DEFAULT_LAUNCHD_INTERVAL,
) -> None:
    console.print(f"[green]✓ macOS launchd plist generated at:[/green] {plist_path}")
    console.print(
        f"[green]✓ update-ip will run once every {interval_seconds} seconds.[/green]"
    )
    console.print("\n[bold cyan]Easy service commands:[/bold cyan]")
    console.print("  uv run update-ip start")
    console.print("  uv run update-ip stop")
    console.print("  uv run update-ip service-status")
    console.print("\n[bold]Log files location:[/bold]")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stdout.log")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stderr.log\n")


if __name__ == "__main__":
    path = generate_plist()
    print_service_instructions(path)
