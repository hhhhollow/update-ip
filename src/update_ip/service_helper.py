import os
import shutil
import sys
from pathlib import Path
from rich.console import Console

console = Console()

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
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
</dict>
</plist>
"""


def generate_plist(target_path: Path | None = None) -> Path:
    working_dir = Path.cwd().resolve()
    log_dir = working_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    uv_path = shutil.which("uv") or "uv"

    content = PLIST_TEMPLATE.format(
        working_dir=str(working_dir),
        uv_path=uv_path,
        log_dir=str(log_dir),
    )

    if target_path is None:
        launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        target_path = launch_agents_dir / "com.update-ip.monitor.plist"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return target_path


def print_service_instructions(plist_path: Path) -> None:
    console.print(f"[green]✓ macOS launchd plist generated at:[/green] {plist_path}")
    console.print("\n[bold cyan]To start the background service immediately and on login:[/bold cyan]")
    console.print(f"  launchctl load -w {plist_path}")
    console.print("\n[bold yellow]To stop and disable the background service:[/bold yellow]")
    console.print(f"  launchctl unload -w {plist_path}")
    console.print("\n[bold]Log files location:[/bold]")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stdout.log")
    console.print(f"  tail -f {Path.cwd().resolve()}/logs/stderr.log\n")


if __name__ == "__main__":
    path = generate_plist()
    print_service_instructions(path)
