from pathlib import Path

import pytest
import respx

from update_ip.config import Settings
from update_ip.monitor import IPMonitor


@pytest.mark.asyncio
async def test_monitor_startup_first_run(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    settings = Settings(
        bark_key="dummy_key",
        cache_file=cache_file,
        ip_providers=["https://mock.ip/current"],
        notify_on_start=True,
    )
    monitor = IPMonitor(settings)

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/current").respond(200, text="123.123.123.123")
        respx_mock.post("https://api.day.app/push").respond(200, json={"code": 200, "message": "success"})
        changed, cur_ip, prev_ip = await monitor.check_once(is_startup=True)

    assert changed is False
    assert cur_ip == "123.123.123.123"
    assert prev_ip is None
    assert monitor.state.get_last_ip() == "123.123.123.123"


@pytest.mark.asyncio
async def test_monitor_regular_check_changed(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    settings = Settings(
        bark_key="dummy_key",
        cache_file=cache_file,
        ip_providers=["https://mock.ip/current"],
    )
    monitor = IPMonitor(settings)
    monitor.state.save_ip("123.123.123.123")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/current").respond(200, text="123.123.123.200")
        respx_mock.post("https://api.day.app/push").respond(200, json={"code": 200, "message": "success"})
        changed, cur_ip, prev_ip = await monitor.check_once(is_startup=False)

    assert changed is True
    assert cur_ip == "123.123.123.200"
    assert prev_ip == "123.123.123.123"
    assert monitor.state.get_last_ip() == "123.123.123.200"


@pytest.mark.asyncio
async def test_failed_bark_delivery_does_not_advance_state(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    settings = Settings(
        bark_key="dummy_key",
        cache_file=cache_file,
        ip_providers=["https://mock.ip/current"],
    )
    monitor = IPMonitor(settings)
    monitor.state.save_ip("123.123.123.123")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/current").respond(200, text="123.123.123.200")
        respx_mock.post("https://api.day.app/push").respond(500, text="temporary failure")
        changed, cur_ip, prev_ip = await monitor.check_once(is_startup=False)

    assert changed is True
    assert cur_ip == "123.123.123.200"
    assert prev_ip == "123.123.123.123"
    assert monitor.state.get_last_ip() == "123.123.123.123"


@pytest.mark.asyncio
async def test_unconfigured_bark_does_not_block_state_update(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    settings = Settings(
        bark_key=None,
        cache_file=cache_file,
        ip_providers=["https://mock.ip/current"],
    )
    monitor = IPMonitor(settings)
    monitor.state.save_ip("123.123.123.123")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get("https://mock.ip/current").respond(200, text="123.123.123.200")
        changed, _, _ = await monitor.check_once(is_startup=False)

    assert changed is True
    assert monitor.state.get_last_ip() == "123.123.123.200"
