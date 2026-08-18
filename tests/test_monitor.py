from pathlib import Path

import pytest
import respx

from update_ip.config import Settings
from update_ip.monitor import IPMonitor


DOMESTIC_URL = "https://mock.ip/domestic"
FOREIGN_URL = "https://mock.ip/foreign"
BARK_URL = "https://api.day.app/push"


def make_settings(cache_file: Path, bark_key="dummy_key", notify_on_start=True) -> Settings:
    return Settings(
        bark_key=bark_key,
        cache_file=cache_file,
        domestic_ip_providers=[DOMESTIC_URL],
        ip_providers=[FOREIGN_URL],
        notify_on_start=notify_on_start,
        max_retries_per_provider=1,
    )


@pytest.mark.asyncio
async def test_monitor_startup_first_run(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file))

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.10")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        respx_mock.post(BARK_URL).respond(200, json={"code": 200, "message": "success"})
        results = await monitor.check_once(is_startup=True)

    assert results["domestic"]["initialized"] is True
    assert results["foreign"]["initialized"] is True
    assert monitor.state.get_last_ip("domestic") == "100.64.0.10"
    assert monitor.state.get_last_ip("foreign") == "203.0.113.20"


@pytest.mark.asyncio
async def test_foreign_change_is_tracked_independently(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file))
    monitor.state.save_ip("100.64.0.10", scope="domestic")
    monitor.state.save_ip("203.0.113.20", scope="foreign")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.10")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.21")
        respx_mock.post(BARK_URL).respond(200, json={"code": 200, "message": "success"})
        results = await monitor.check_once(is_startup=False)

    assert results["domestic"]["changed"] is False
    assert results["foreign"]["changed"] is True
    assert monitor.state.get_last_ip("domestic") == "100.64.0.10"
    assert monitor.state.get_last_ip("foreign") == "203.0.113.21"


@pytest.mark.asyncio
async def test_failed_bark_delivery_does_not_advance_changed_channel(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file))
    monitor.state.save_ip("100.64.0.10", scope="domestic")
    monitor.state.save_ip("203.0.113.20", scope="foreign")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.10")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.21")
        respx_mock.post(BARK_URL).respond(500, text="temporary failure")
        results = await monitor.check_once(is_startup=False)

    assert results["foreign"]["changed"] is True
    assert results["foreign"]["state_advanced"] is False
    assert monitor.state.get_last_ip("foreign") == "203.0.113.20"


@pytest.mark.asyncio
async def test_unconfigured_bark_does_not_block_state_updates(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file, bark_key=None))
    monitor.state.save_ip("100.64.0.10", scope="domestic")
    monitor.state.save_ip("203.0.113.20", scope="foreign")

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.11")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.21")
        results = await monitor.check_once(is_startup=False)

    assert results["domestic"]["changed"] is True
    assert results["foreign"]["changed"] is True
    assert monitor.state.get_last_ip("domestic") == "100.64.0.11"
    assert monitor.state.get_last_ip("foreign") == "203.0.113.21"


@pytest.mark.asyncio
async def test_one_channel_failure_does_not_block_the_other(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file, bark_key=None))

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(503)
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        results = await monitor.check_once(is_startup=False)

    assert results["domestic"]["error"] is not None
    assert results["foreign"]["ip"] == "203.0.113.20"
    assert monitor.state.get_last_ip("foreign") == "203.0.113.20"
    assert monitor.state.get_health("domestic")["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_both_channel_failures_are_recorded(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    monitor = IPMonitor(make_settings(cache_file, bark_key=None))

    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(503)
        respx_mock.get(FOREIGN_URL).respond(503)
        results = await monitor.check_once(is_startup=False)

    assert results["domestic"]["error"] is not None
    assert results["foreign"]["error"] is not None
    assert monitor.state.get_health("domestic")["consecutive_failures"] == 1
    assert monitor.state.get_health("foreign")["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_failure_alert_after_three_checks_then_recovery_alert(tmp_path: Path):
    cache_file = tmp_path / "cache.json"

    for attempt in (1, 2):
        monitor = IPMonitor(make_settings(cache_file))
        with respx.mock(assert_all_called=True) as respx_mock:
            respx_mock.get(DOMESTIC_URL).respond(503)
            respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
            await monitor.check_once(is_startup=False)
        assert monitor.state.get_health("domestic")["consecutive_failures"] == attempt
        assert monitor.state.get_health("domestic")["alert_active"] is False

    monitor = IPMonitor(make_settings(cache_file))
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(503)
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        failure_push = respx_mock.post(BARK_URL).respond(
            200,
            json={"code": 200, "message": "success"},
        )
        await monitor.check_once(is_startup=False)

    assert failure_push.call_count == 1
    health = monitor.state.get_health("domestic")
    assert health["consecutive_failures"] == 3
    assert health["alert_active"] is True
    assert health["outage_failure_count"] == 3

    monitor = IPMonitor(make_settings(cache_file))
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(503)
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        await monitor.check_once(is_startup=False)

    health = monitor.state.get_health("domestic")
    assert health["consecutive_failures"] == 4
    assert health["alert_active"] is True
    assert health["outage_failure_count"] == 4

    monitor = IPMonitor(make_settings(cache_file))
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.10")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        recovery_push = respx_mock.post(BARK_URL).respond(
            200,
            json={"code": 200, "message": "success"},
        )
        results = await monitor.check_once(is_startup=False)

    assert recovery_push.call_count == 1
    assert results["domestic"]["ip"] == "100.64.0.10"
    recovered_health = monitor.state.get_health("domestic")
    assert recovered_health["consecutive_failures"] == 0
    assert recovered_health["alert_active"] is False
    assert recovered_health["outage_failure_count"] == 0

    monitor = IPMonitor(make_settings(cache_file))
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.get(DOMESTIC_URL).respond(200, text="100.64.0.10")
        respx_mock.get(FOREIGN_URL).respond(200, text="203.0.113.20")
        await monitor.check_once(is_startup=False)

    assert monitor.state.get_health("domestic")["alert_active"] is False
