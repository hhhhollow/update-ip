from pathlib import Path
from update_ip.state_manager import StateManager


def test_state_manager_empty(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)
    assert manager.get_last_ip() is None

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
    assert len(data["history"]) == 1
    assert data["history"][0]["ip"] == "1.1.1.1"
    assert data["history"][0]["provider"] == "https://test.ip"

    # Save second IP
    manager.save_ip("2.2.2.2", provider="https://test.ip/2")
    assert manager.get_last_ip() == "2.2.2.2"

    data2 = manager.load()
    assert len(data2["history"]) == 2
    assert data2["history"][1]["previous_ip"] == "1.1.1.1"
    assert data2["history"][1]["ip"] == "2.2.2.2"


def test_state_manager_history_limit(tmp_path: Path):
    cache_file = tmp_path / "cache.json"
    manager = StateManager(cache_file)

    for i in range(60):
        manager.save_ip(f"10.0.0.{i}")

    data = manager.load()
    assert len(data["history"]) == 50
    assert data["last_ip"] == "10.0.0.59"
    assert data["history"][-1]["ip"] == "10.0.0.59"
