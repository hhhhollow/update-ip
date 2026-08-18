import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger("update_ip.state")


class StateManager:
    def __init__(self, cache_file: Path):
        self.cache_file = Path(cache_file)

    def load(self) -> Dict[str, Any]:
        if not self.cache_file.exists():
            return {"last_ip": None, "last_updated": None, "history": []}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {"last_ip": None, "last_updated": None, "history": []}
                return data
        except Exception as e:
            logger.warning(f"Failed to read cache file {self.cache_file}: {e}. Initializing empty state.")
            return {"last_ip": None, "last_updated": None, "history": []}

    def get_last_ip(self) -> Optional[str]:
        data = self.load()
        return data.get("last_ip")

    def save_ip(self, ip: str, provider: Optional[str] = None) -> None:
        data = self.load()
        now_iso = datetime.now(timezone.utc).astimezone().isoformat()
        old_ip = data.get("last_ip")

        data["last_ip"] = ip
        data["last_updated"] = now_iso

        history: List[Dict[str, Any]] = data.get("history", [])
        if not isinstance(history, list):
            history = []

        history.append({
            "ip": ip,
            "previous_ip": old_ip,
            "timestamp": now_iso,
            "provider": provider,
        })
        # Keep the latest 50 history entries
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
