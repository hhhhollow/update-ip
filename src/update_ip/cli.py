import argparse
import asyncio
import logging
import sys

from update_ip.config import get_settings
from update_ip.monitor import IPMonitor, setup_logging
from update_ip.service_helper import (
    DEFAULT_LAUNCHD_INTERVAL,
    generate_plist,
    print_service_instructions,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-ip",
        description="Public IP change monitor daemon with Bark push notifications",
    )
    parser.add_argument("-k", "--key", dest="bark_key", help="Bark device key (overrides .env)")
    parser.add_argument("-s", "--server", dest="bark_server", help="Bark server URL")
    parser.add_argument("-i", "--interval", type=int, dest="check_interval", help="Check interval in seconds")
    parser.add_argument(
        "--ip-version",
        choices=["4", "6", "any"],
        dest="ip_version",
        help="IP address family to monitor: 4, 6, or any (default: 4)",
    )
    parser.add_argument("-c", "--config", dest="config_file", help="Path to custom .env file")
    parser.add_argument("--once", action="store_true", help="Run a single IP check and exit")
    parser.add_argument("--test", action="store_true", help="Run provider diagnostics and test Bark")
    parser.add_argument("--status", action="store_true", help="Show cached IP and recent history")
    parser.add_argument("--generate-launchd", action="store_true", help="Generate macOS launchd plist")
    parser.add_argument(
        "--launchd-interval",
        type=int,
        default=DEFAULT_LAUNCHD_INTERVAL,
        help="macOS launchd schedule interval in seconds (default: 300)",
    )
    parser.add_argument("--notify-on-start", action="store_true", default=None)
    parser.add_argument("--no-notify-on-start", action="store_false", dest="notify_on_start")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logs")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.generate_launchd:
        if args.launchd_interval < 1:
            parser.error("--launchd-interval must be at least 1 second")
        plist_path = generate_plist(interval_seconds=args.launchd_interval)
        print_service_instructions(plist_path, args.launchd_interval)
        sys.exit(0)

    settings = get_settings(env_file=args.config_file)

    overrides = {}
    if args.bark_key:
        overrides["bark_key"] = args.bark_key
    if args.bark_server:
        overrides["bark_server"] = args.bark_server
    if args.check_interval is not None:
        overrides["check_interval"] = args.check_interval
    if args.ip_version:
        overrides["ip_version"] = args.ip_version
    if args.notify_on_start is not None:
        overrides["notify_on_start"] = args.notify_on_start
    if overrides:
        settings = settings.model_copy(update=overrides)
        settings = type(settings).model_validate(settings.model_dump())

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
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
            if prev_ip is None:
                print(f"Current IP: {cur_ip} (Initialized)")
            else:
                print(f"Current IP: {cur_ip} (Changed: {changed})")
            sys.exit(0)
        except Exception as e:
            print(f"Error checking IP: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        asyncio.run(monitor.run_forever())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
