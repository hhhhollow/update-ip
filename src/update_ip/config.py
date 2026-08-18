from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bark_key: Optional[str] = Field(default=None)
    bark_server: str = Field(default="https://api.day.app")
    bark_group: str = Field(default="IP-Monitor")
    bark_sound: Optional[str] = Field(default=None)
    bark_icon: Optional[str] = Field(
        default="https://cdn-icons-png.flaticon.com/512/2920/2920244.png"
    )
    bark_level: Literal["active", "timeSensitive", "passive"] = Field(default="active")

    check_interval: int = Field(default=60, ge=1)
    notify_on_start: bool = Field(default=True)
    cache_file: Path = Field(default=Path(".ip_cache.json"))
    request_timeout: float = Field(default=10.0, gt=0)
    max_retries_per_provider: int = Field(default=2, ge=1, le=10)
    ip_version: Literal["4", "6", "any"] = Field(default="4")

    ip_providers: List[str] = Field(
        default_factory=lambda: [
            "https://api64.ipify.org?format=json",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
            "https://ident.me",
            "https://api.ipify.org",
            "https://ip.sb",
            "https://cip.cc",
        ]
    )


def get_settings(env_file: Optional[str] = None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()
