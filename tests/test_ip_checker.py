import pytest
import respx

from update_ip.ip_checker import IPChecker, extract_and_validate_ip


def test_extract_and_validate_ip():
    assert extract_and_validate_ip("192.168.1.1") == "192.168.1.1"
    assert extract_and_validate_ip("IP: 123.45.67.89\nCountry: CN") == "123.45.67.89"
    assert extract_and_validate_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334") == "2001:db8:85a3::8a2e:370:7334"
    assert extract_and_validate_ip("999.999.999.999") is None


def test_extract_respects_ip_version():
    assert extract_and_validate_ip("2001:db8::1", "4") is None
    assert extract_and_validate_ip("203.0.113.5", "6") is None
    assert extract_and_validate_ip("203.0.113.5", "4") == "203.0.113.5"


@pytest.mark.asyncio
async def test_ip_checker_plain_text():
    checker = IPChecker(providers=["https://mock.ip/text"], max_retries_per_provider=1)
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/text").respond(200, text="203.0.113.195\n")
        ip, provider = await checker.get_current_ip()
        assert ip == "203.0.113.195"
        assert provider == "https://mock.ip/text"


@pytest.mark.asyncio
async def test_ip_checker_rejects_wrong_address_family_and_fails_over():
    checker = IPChecker(
        providers=["https://mock.ip/v6", "https://mock.ip/v4"],
        max_retries_per_provider=1,
        ip_version="4",
    )
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/v6").respond(200, text="2001:db8::1")
        respx_mock.get("https://mock.ip/v4").respond(200, text="198.51.100.99")
        ip, provider = await checker.get_current_ip()
        assert ip == "198.51.100.99"
        assert provider == "https://mock.ip/v4"


@pytest.mark.asyncio
async def test_ip_checker_json_response():
    checker = IPChecker(providers=["https://mock.ip/json"], max_retries_per_provider=1)
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/json").respond(200, json={"ip": "198.51.100.42"})
        ip, provider = await checker.get_current_ip()
        assert ip == "198.51.100.42"
        assert provider == "https://mock.ip/json"


@pytest.mark.asyncio
async def test_ip_checker_all_fail():
    checker = IPChecker(
        providers=["https://mock.ip/fail1", "https://mock.ip/fail2"],
        max_retries_per_provider=1,
    )
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/fail1").respond(502)
        respx_mock.get("https://mock.ip/fail2").respond(503)
        with pytest.raises(RuntimeError, match="All IP providers failed"):
            await checker.get_current_ip()
