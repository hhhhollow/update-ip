import plistlib
from types import SimpleNamespace

import pytest

from update_ip import service_helper
from update_ip.service_helper import generate_plist


def test_generate_plist_schedules_single_check_every_five_minutes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "com.update-ip.monitor.plist"

    generate_plist(target)

    plist = plistlib.loads(target.read_bytes())
    assert plist["RunAtLoad"] is True
    assert plist["StartInterval"] == 300
    assert plist["ProgramArguments"][-2:] == ["update-ip", "--once"]
    assert "KeepAlive" not in plist


def test_generate_plist_supports_custom_interval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "com.update-ip.monitor.plist"

    generate_plist(target, interval_seconds=600)

    plist = plistlib.loads(target.read_bytes())
    assert plist["StartInterval"] == 600


def test_generate_plist_rejects_non_positive_interval(tmp_path):
    target = tmp_path / "com.update-ip.monitor.plist"

    with pytest.raises(ValueError, match="at least 1 second"):
        generate_plist(target, interval_seconds=0)


def test_start_service_reloads_launch_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.update-ip.monitor.plist"
    monkeypatch.setattr(service_helper, "default_plist_path", lambda: plist_path)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_helper.subprocess, "run", fake_run)

    service_helper.start_service()

    assert calls[0][:3] == ["launchctl", "unload", "-w"]
    assert calls[1][:3] == ["launchctl", "load", "-w"]
    assert plist_path.exists()


def test_stop_service_unloads_launch_agent(tmp_path, monkeypatch):
    plist_path = tmp_path / "com.update-ip.monitor.plist"
    plist_path.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(service_helper, "default_plist_path", lambda: plist_path)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service_helper.subprocess, "run", fake_run)

    assert service_helper.stop_service() is True
    assert calls == [["launchctl", "unload", "-w", str(plist_path)]]


def test_service_status_uses_launchctl_list(monkeypatch):
    def fake_run(args, **kwargs):
        assert args == ["launchctl", "list", "com.update-ip.monitor"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(service_helper.subprocess, "run", fake_run)

    assert service_helper.service_is_running() is True
