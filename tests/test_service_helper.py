import plistlib

import pytest

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
