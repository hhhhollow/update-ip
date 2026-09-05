from unittest.mock import AsyncMock, Mock

import pytest

from update_ip import cli


@pytest.mark.parametrize("command", ["start", "--generate-launchd"])
@pytest.mark.parametrize("notify_flag", ["--notify-on-start", "--no-notify-on-start"])
def test_service_commands_forward_monitor_options(tmp_path, monkeypatch, command, notify_flag):
    monkeypatch.chdir(tmp_path)
    service = Mock(return_value=tmp_path / "monitor.plist")
    instructions = Mock()
    monkeypatch.setattr(cli, "start_service", service)
    monkeypatch.setattr(cli, "generate_plist", service)
    monkeypatch.setattr(cli, "print_service_instructions", instructions)
    settings = Mock(side_effect=AssertionError("service commands must not load settings"))
    monkeypatch.setattr(cli, "get_settings", settings)
    monkeypatch.setattr(cli.sys, "argv", [
        "update-ip", command,
        "--config", "custom.env",
        "--key", "test-key",
        "--server", "https://bark.example",
        "--interval", "45",
        "--ip-version", "6",
        notify_flag,
        "--verbose",
        "--launchd-interval", "600",
    ])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    service.assert_called_once_with(interval_seconds=600, monitor_args=[
        "--config", str(tmp_path / "custom.env"),
        "--key", "test-key",
        "--server", "https://bark.example",
        "--interval", "45",
        "--ip-version", "6",
        notify_flag,
        "--verbose",
    ])
    settings.assert_not_called()
    if command == "--generate-launchd":
        instructions.assert_called_once_with(tmp_path / "monitor.plist", 600)


@pytest.mark.parametrize("command", ["stop", "service-status"])
def test_service_control_does_not_load_settings(monkeypatch, command):
    service = Mock()
    monkeypatch.setattr(cli, "stop_service", service)
    monkeypatch.setattr(cli, "print_service_status", service)
    monkeypatch.setattr(
        cli, "get_settings", Mock(side_effect=AssertionError("unexpected settings load"))
    )
    monkeypatch.setattr(cli.sys, "argv", ["update-ip", command])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    service.assert_called_once_with()


def test_once_cli_override_replaces_invalid_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHECK_INTERVAL", "0")
    monkeypatch.setattr(cli.sys, "argv", ["update-ip", "--once", "--interval", "60"])
    monkeypatch.setattr(cli, "setup_logging", Mock())
    monitor = Mock()
    monitor.check_once = AsyncMock(return_value={
        "domestic": {"ip": "192.0.2.1", "error": None},
        "foreign": {"ip": "198.51.100.1", "error": None},
    })
    monitor_class = Mock(return_value=monitor)
    monkeypatch.setattr(cli, "IPMonitor", monitor_class)

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert monitor_class.call_args.args[0].check_interval == 60
    monitor.check_once.assert_awaited_once_with(is_startup=False)
