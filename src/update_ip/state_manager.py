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
    def _empty_state() -> Dict[str, Any]:
        return {
            "last_ip": None,
            "last_domestic_ip": None,
            "last_foreign_ip": None,
            "last_updated": None,
            "last_domestic_updated": None,
            "last_foreign_updated": None,
            "history": [],
        }

    @staticmethod
    def _validate_scope(scope: str) -> None:
        if scope not in _VALID_SCOPES:
            raise ValueError("scope must be 'domestic' or 'foreign'")

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
