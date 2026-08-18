import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("update_ip.state")

_VALID_SCOPES = {"domestic", "foreign"}


class StateManager:
    def __init__(self, cache_file: Path):
        self.cache_file = Path(cache_file)

    @staticmethod
    def _empty_health_channel() -> Dict[str, Any]:
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
    def _empty_state(cls) -> Dict[str, Any]:
        return {
            "last_ip": None,
            "last_domestic_ip": None,
            "last_foreign_ip": None,
            "last_updated": None,
            "last_domestic_updated": None,
            "last_foreign_updated": None,
            "history": [],
            "health": {
                "domestic": cls._empty_health_channel(),
                "foreign": cls._empty_health_channel(),
            },
        }

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if scope not in _VALID_SCOPES:
            raise ValueError("scope must be 'domestic' or 'foreign'")

    def _health_channel_from_data(self, data: Dict[str, Any], scope: str) -> Dict[str, Any]:
        self._validate_scope(scope)
        health = data.get("health")
        if not isinstance(health, dict):
            health = {}

        channel = self._empty_health_channel()
        raw_channel = health.get(scope)
        if isinstance(raw_channel, dict):
            channel.update(raw_channel)

        try:
            channel["consecutive_failures"] = max(0, int(channel["consecutive_failures"]))
        except (TypeError, ValueError):
            channel["consecutive_failures"] = 0
        try:
            channel["outage_failure_count"] = max(0, int(channel["outage_failure_count"]))
        except (TypeError, ValueError):
            channel["outage_failure_count"] = 0
        channel["alert_active"] = bool(channel["alert_active"])
        return channel

    def _store_health_channel(
        self,
        data: Dict[str, Any],
        scope: str,
        channel: Dict[str, Any],
    ) -> None:
        health = data.get("health")
        if not isinstance(health, dict):
            health = {}
        health[scope] = channel
        data["health"] = health

    def load(self) -> Dict[str, Any]:
        if not self.cache_file.exists():
            return self._empty_state()
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return self._empty_state()
                merged = self._empty_state()
                merged.update(data)
                return merged
        except Exception as e:
            logger.warning(f"Failed to read cache file {self.cache_file}: {e}. Initializing empty state.")
            return self._empty_state()

    def get_last_ip(self, scope: str = "foreign") -> Optional[str]:
        self._validate_scope(scope)
        data = self.load()
        if scope == "domestic":
            return data.get("last_domestic_ip")

        # Backwards compatibility: before dual-channel monitoring, last_ip was
        # the only cached address. Treat it as the foreign/proxy-exit baseline.
        return data.get("last_foreign_ip") or data.get("last_ip")

    def get_health(self, scope: str) -> Dict[str, Any]:
        data = self.load()
        return self._health_channel_from_data(data, scope)

    def record_failure(self, scope: str, error: str) -> Dict[str, Any]:
        self._validate_scope(scope)
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()

        channel["consecutive_failures"] += 1
        channel["last_error"] = str(error)
        channel["last_failure_at"] = now_iso
        if channel["alert_active"]:
            channel["outage_failure_count"] = channel["consecutive_failures"]

        self._store_health_channel(data, scope, channel)
        self._atomic_save(data)
        return dict(channel)

    def mark_failure_alerted(self, scope: str) -> Dict[str, Any]:
        self._validate_scope(scope)
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()

        channel["alert_active"] = True
        channel["outage_failure_count"] = channel["consecutive_failures"]
        channel["alerted_at"] = now_iso

        self._store_health_channel(data, scope, channel)
        self._atomic_save(data)
        return dict(channel)

    def record_success(self, scope: str) -> Dict[str, Any]:
        self._validate_scope(scope)
        data = self.load()
        channel = self._health_channel_from_data(data, scope)
        previous_failures = channel["consecutive_failures"]
        alert_active = channel["alert_active"]

        if previous_failures == 0 and not alert_active:
            result = dict(channel)
            result["previous_failures"] = 0
            return result

        channel["consecutive_failures"] = 0
        channel["last_error"] = None
        channel["last_success_at"] = datetime.now(timezone.utc).astimezone().isoformat()

        if not alert_active:
            channel["outage_failure_count"] = 0
            channel["alerted_at"] = None

        self._store_health_channel(data, scope, channel)
        self._atomic_save(data)

        result = dict(channel)
        result["previous_failures"] = previous_failures
        return result

    def clear_failure_alert(self, scope: str) -> Dict[str, Any]:
        self._validate_scope(scope)
        data = self.load()
        channel = self._health_channel_from_data(data, scope)

        channel["alert_active"] = False
        channel["outage_failure_count"] = 0
        channel["alerted_at"] = None
        channel["last_error"] = None

        self._store_health_channel(data, scope, channel)
        self._atomic_save(data)
        return dict(channel)

    def save_ip(self, ip: str, provider: Optional[str] = None, scope: str = "foreign") -> None:
        self._validate_scope(scope)
        data = self.load()
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()

        key = f"last_{scope}_ip"
        old_ip = data.get(key)
        if scope == "foreign" and old_ip is None:
            old_ip = data.get("last_ip")

        data[key] = ip
        data[f"last_{scope}_updated"] = now_iso
        data["last_updated"] = now_iso

        # Preserve last_ip as a compatibility alias for the foreign/proxy IP.
        if scope == "foreign":
            data["last_ip"] = ip

        history: List[Dict[str, Any]] = data.get("history", [])
        if not isinstance(history, list):
            history = []

        history.append({
            "ip": ip,
            "previous_ip": old_ip,
            "timestamp": now_iso,
            "provider": provider,
            "scope": scope,
        })
        data["history"] = history[-50:]

        self._atomic_save(data)

    def _atomic_save(self, data: Dict[str, Any]) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.cache_file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.cache_file)
        except Exception as e:
            logger.error(f"Failed to write cache to {self.cache_file}: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass
            raise
