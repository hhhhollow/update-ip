import pytest
from pydantic import ValidationError

from update_ip.config import Settings, get_settings


def test_rejects_zero_interval():
    with pytest.raises(ValidationError):
        Settings(check_interval=0)


def test_rejects_zero_timeout():
    with pytest.raises(ValidationError):
        Settings(request_timeout=0)


def test_rejects_invalid_ip_version():
    with pytest.raises(ValidationError):
        Settings(ip_version="5")


def test_default_ip_version_is_ipv4():
    assert Settings().ip_version == "4"


def test_has_separate_domestic_and_foreign_providers():
    settings = Settings()
    assert "https://4.ipw.cn" in settings.domestic_ip_providers
    assert "https://api.ipify.org" in settings.ip_providers


@pytest.mark.parametrize("source", ["dotenv", "environment"])
def test_overrides_apply_before_validation(tmp_path, monkeypatch, source):
    env_file = tmp_path / "custom.env"
    env_file.write_text("NOTIFY_ON_START=false\n", encoding="utf-8")
    if source == "dotenv":
        env_file.write_text("CHECK_INTERVAL=0\nNOTIFY_ON_START=false\n", encoding="utf-8")
    else:
        monkeypatch.setenv("CHECK_INTERVAL", "0")

    settings = get_settings(env_file=str(env_file), check_interval=60)

    assert settings.check_interval == 60
    assert settings.notify_on_start is False
