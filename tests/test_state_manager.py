from pathlib import Path

from update_ip.state_manager import StateManager


def test_state_manager_empty(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)
    assert manager.get_last_ip() is None
    assert manager.get_last_ip("domestic") is None

    data = manager.load()
    assert data["last_ip"] is None
    assert data["history"] == []


def test_state_manager_save_and_load(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)

    manager.save_ip("1.1.1.1", provider="https://test.ip")
    assert manager.get_last_ip() == "1.1.1.1"

    data = manager.load()
    assert data["last_ip"] == "1.1.1.1"
    assert data["last_foreign_ip"] == "1.1.1.1"
    assert len(data["history"]) == 1
    assert data["history"][0]["ip"] == "1.1.1.1"
    assert data["history"][0]["provider"] == "https://test.ip"
    assert data["history"][0]["scope"] == "foreign"

    manager.save_ip("2.2.2.2", provider="https://test.ip/2")
    assert manager.get_last_ip() == "2.2.2.2"

    data2 = manager.load()
    assert len(data2["history"]) == 2
    assert data2["history"][1]["previous_ip"] == "1.1.1.1"
    assert data2["history"][1]["ip"] == "2.2.2.2"


def test_domestic_and_foreign_state_are_independent(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)

    manager.save_ip("100.64.0.10", provider="https://cn.example", scope="domestic")
    manager.save_ip("203.0.113.20", provider="https://global.example", scope="foreign")

    assert manager.get_last_ip("domestic") == "100.64.0.10"
    assert manager.get_last_ip("foreign") == "203.0.113.20"

    data = manager.load()
    assert data["last_domestic_ip"] == "100.64.0.10"
    assert data["last_foreign_ip"] == "203.0.113.20"
    assert data["last_ip"] == "203.0.113.20"
    assert [item["scope"] for item in data["history"]] == ["domestic", "foreign"]


def test_legacy_last_ip_is_used_as_foreign_baseline(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"last_ip": "198.51.100.5", "last_updated": null, "history": []}',
        encoding="utf-8",
    )
    manager = StateManager(cache_file)

    assert manager.get_last_ip("foreign") == "198.51.100.5"
    assert manager.get_last_ip("domestic") is None


def test_state_manager_history_limit(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)

    for i in range(60):
        manager.save_ip(f"10.0.0.{i}")

    data = manager.load()
    assert len(data["history"]) == 50
    assert data["last_ip"] == "10.0.0.59"
    assert data["history"][-1]["ip"] == "10.0.0.59"
