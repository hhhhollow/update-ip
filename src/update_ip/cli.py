import argparse
import asyncio
import logging
import sys
from pathlib import Path

from update_ip.config import get_settings
from update_ip.monitor import IPMonitor, setup_logging
from update_ip.service_helper import generate_plist, print_service_instructions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-ip",
        description="Public IP change monitor daemon with Bark push notifications",
    )
    parser.add_argument(
        "-k", "--key",
        dest="bark_key",
        help="Bark device key (overrides .env)",
    )
    parser.add_argument(
        "-s", "--server",
        dest="bark_server",
        help="Bark server URL (e.g. https://api.day.app)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=int,
        dest="check_interval",
        help="Check interval in seconds (default: 60)",
    )
    parser.add_argument(
        "-c", "--config",
        dest="config_file",
        help="Path to custom .env file",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single IP check, notify if changed, and exit",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run provider diagnostics and test Bark notification",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current cached IP and recent change history",
    )
    parser.add_argument(
        "--generate-launchd",
        action="store_true",
        help="Generate macOS launchd plist file for background auto-start",
    )
    parser.add_argument(
        "--notify-on-start",
        action="store_true",
        default=None,
        help="Send a Bark notification when monitor starts",
    )
    parser.add_argument(
        "--no-notify-on-start",
        action="store_false",
        dest="notify_on_start",
        help="Do not send a Bark notification on monitor startup",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug level logs",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # If generating launchd service
    if args.generate_launchd:
        plist_path = generate_plist()
        print_service_instructions(plist_path)
        sys.exit(0)

    # Load configuration
    settings = get_settings(env_file=args.config_file)

    # Apply CLI overrides
    if args.bark_key:
        settings.bark_key = args.bark_key
    if args.bark_server:
        settings.bark_server = args.bark_server
    if args.check_interval:
        settings.check_interval = args.check_interval
    if args.notify_on_start is not None:
        settings.notify_on_start = args.notify_on_start

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(log_level)

    monitor = IPMonitor(settings)

    if args.status:
        monitor.show_status()
        sys.exit(0)

    if args.test:
        asyncio.run(monitor.test())
        sys.exit(0)

    if args.once:
        try:
            changed, cur_ip, prev_ip = asyncio.run(monitor.check_once(is_startup=False))
            print(f"Current IP: {cur_ip} (Changed: {changed})")
            sys.exit(0)
        except Exception as e:
            print(f"Error checking IP: {e}", file=sys.stderr)
            sys.exit(1)

    # Run continuous daemon
    try:
        asyncio.run(monitor.run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
