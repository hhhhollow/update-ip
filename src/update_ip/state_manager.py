import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("update_ip.state")

SCOPES = ("domestic", "foreign")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class StateManager:
    def __init__(self, cache_file: Path):
        self.cache_file = Path(cache_file)

    @staticmethod
    def _empty_health_channel() -> dict[str, Any]:
        return {
            "consecutive_failures": 0,
            "alert_active": False,
            "outage_failure_count": 0,
            "last_error": None,
            "last_failure_at": None,
            "alerted_at": None,
            "last_success_at": None,
        }

    @classmethod
    def _empty_state(cls) -> dict[str, Any]:
        return {
            "last_ip": None,
            "last_domestic_ip": None,
            "last_foreign_ip": None,
            "last_updated": None,
            "last_domestic_updated": None,
            "last_foreign_updated": None,
            "history": [],
            "health": {scope: cls._empty_health_channel() for scope in SCOPES},
        }

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if scope not in SCOPES:
            raise ValueError("scope must be 'domestic' or 'foreign'")

    def _health_channel_from_data(self, data: dict[str, Any], scope: str) -> dict[str, Any]:
        self._validate_scope(scope)
        channel = self._empty_health_channel()
        health = data.get("health")
        if isinstance(health, dict) and isinstance(health.get(scope), dict):
            channel.update(health[scope])

        for key in ("consecutive_failures", "outage_failure_count"):
            try:
                channel[key] = max(0, int(channel[key]))
            except (TypeError, ValueError):
                channel[key] = 0
        channel["alert_active"] = bool(channel["alert_active"])
        return channel

    def _save_health(self, data: dict[str, Any], scope: str, channel: dict[str, Any]) -> None:
        health = data.get("health")
        if not isinstance(health, dict):
            health = {}
        health[scope] = channel
        data["health"] = health
        self._atomic_save(data)

    def load(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return self._empty_state()
        try:
            with self.cache_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                return self._empty_state()
            return self._empty_state() | data
        except Exception as exc:
            logger.warning(
                "Failed to read cache file %s: %s. Initializing empty state.",
                self.cache_file,
                exc,
            )
            return self._empty_state()

    def get_last_ip(self, scope: str = "foreign") -> str | None:
        self._validate_scope(scope)
        data = self.load()
        if scope == "domestic":
            return data.get("last_domestic_ip")
        return data.get("last_foreign_ip") or data.get("last_ip")

    def get_health(self, scope: str) -> dict[str, Any]:
        return self._health_channel_from_data(self.load(), scope)

    def record_failure(self, scope: str, error: str) -> dict[str, Any]:
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        channel["consecutive_failures"] += 1
        channel["last_error"] = str(error)
        channel["last_failure_at"] = _now()
        if channel["alert_active"]:
            channel["outage_failure_count"] = channel["consecutive_failures"]
        self._save_health(data, scope, channel)
        return dict(channel)

    def mark_failure_alerted(self, scope: str) -> dict[str, Any]:
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        channel.update(
            alert_active=True,
            outage_failure_count=channel["consecutive_failures"],
            alerted_at=_now(),
        )
        self._save_health(data, scope, channel)
        return dict(channel)

    def record_success(self, scope: str) -> dict[str, Any]:
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        previous_failures = channel["consecutive_failures"]
        if previous_failures == 0 and not channel["alert_active"]:
            return dict(channel, previous_failures=0)

        channel.update(
            consecutive_failures=0,
            last_error=None,
            last_success_at=_now(),
        )
        if not channel["alert_active"]:
            channel.update(outage_failure_count=0, alerted_at=None)
        self._save_health(data, scope, channel)
        return dict(channel, previous_failures=previous_failures)

    def clear_failure_alert(self, scope: str) -> dict[str, Any]:
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        channel.update(
            alert_active=False,
            outage_failure_count=0,
            alerted_at=None,
            last_error=None,
        )
        self._save_health(data, scope, channel)
        return dict(channel)

    def save_ip(self, ip: str, provider: str | None = None, scope: str = "foreign") -> None:
        self._validate_scope(scope)
        data = self.load()
        key = f"last_{scope}_ip"
        old_ip = data.get(key) or (data.get("last_ip") if scope == "foreign" else None)
        now = _now()

        data.update({key: ip, f"last_{scope}_updated": now, "last_updated": now})
        if scope == "foreign":
            data["last_ip"] = ip

        history = data.get("history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "ip": ip,
                "previous_ip": old_ip,
                "timestamp": now,
                "provider": provider,
                "scope": scope,
            }
        )
        data["history"] = history[-50:]
        self._atomic_save(data)

    def _atomic_save(self, data: dict[str, Any]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.cache_file.with_suffix(".tmp")
        try:
            with tmp_file.open("w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.cache_file)
        except Exception:
            logger.exception("Failed to write cache to %s", self.cache_file)
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
            raise
