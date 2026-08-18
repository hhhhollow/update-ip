import pytest
from pydantic import ValidationError

from update_ip.config import Settings


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
