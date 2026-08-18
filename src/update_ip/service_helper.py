import shutil
from pathlib import Path

from rich.console import Console

console = Console()

DEFAULT_LAUNCHD_INTERVAL = 300

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.update-ip.monitor</string>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{uv_path}</string>
        <string>run</string>
        <string>--directory</string>
        <string>{working_dir}</string>
        <string>update-ip</string>
        <string>--once</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
</dict>
</plist>
"""


def generate_plist(
    target_path: Path | None = None,
    interval_seconds: int = DEFAULT_LAUNCHD_INTERVAL,
) -> Path:
    if interval_seconds < 1:
        raise ValueError("launchd interval must be at least 1 second")

    working_dir = Path.cwd().resolve()
    log_dir = working_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    uv_path = shutil.which("uv") or "uv"

    content = PLIST_TEMPLATE.format(
        working_dir=str(working_dir),
        uv_path=uv_path,
        log_dir=str(log_dir),
        interval_seconds=interval_seconds,
    )

    if target_path is None:
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        target_path = launch_agents_dir / "com.update-ip.monitor.plist"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return target_path


def print_service_instructions(
    plist_path: Path,
    interval_seconds: int = DEFAULT_LAUNCHD_INTERVAL,
) -> None:
    console.print(f"[green]✓ macOS launchd plist generated at:[/green] {plist_path}")
    console.print(
        f"[green]✓ update-ip will run once every {interval_seconds} seconds.[/green]"
    )
    console.print("\n[bold cyan]To load or reload the scheduled job:[/bold cyan]")
    console.print(f"  launchctl unload -w {plist_path} 2>/dev/null || true")
    console.print(f"  launchctl load -w {plist_path}")
    console.print("\n[bold yellow]To stop and disable the scheduled job:[/bold yellow]")
    console.print(f"  launchctl unload -w {plist_path}")
    console.print("\n[bold]Log files location:[/bold]")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stdout.log")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stderr.log\n")


if __name__ == "__main__":
    path = generate_plist()
    print_service_instructions(path)
