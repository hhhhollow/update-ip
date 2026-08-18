from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bark Configuration
    bark_key: Optional[str] = Field(
        default=None,
        description="Bark device key (e.g. from Bark iOS app)",
    )
    bark_server: str = Field(
        default="https://api.day.app",
        description="Bark server URL",
    )
    bark_group: str = Field(
        default="IP-Monitor",
        description="Notification group name in Bark",
    )
    bark_sound: Optional[str] = Field(
        default=None,
        description="Notification sound (e.g. minuet, alarm, bell)",
    )
    bark_icon: Optional[str] = Field(
        default="https://cdn-icons-png.flaticon.com/512/2920/2920244.png",
        description="Notification icon URL",
    )
    bark_level: str = Field(
        default="active",
        description="Notification level: active, timeSensitive, or passive",
    )

    # Monitor Configuration
    check_interval: int = Field(
        default=60,
        description="Interval in seconds between IP checks",
    )
    notify_on_start: bool = Field(
        default=True,
        description="Whether to send a notification when the monitor starts",
    )
    cache_file: Path = Field(
        default=Path(".ip_cache.json"),
        description="Path to local cache file storing last known IP",
    )
    request_timeout: float = Field(
        default=10.0,
        description="Network request timeout in seconds",
    )
    max_retries_per_provider: int = Field(
        default=2,
        description="Max retries per IP provider before failing over",
    )

    # IP Providers (Failover list)
    ip_providers: List[str] = Field(
        default_factory=lambda: [
            "https://api64.ipify.org?format=json",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
            "https://ident.me",
            "https://api.ipify.org",
            "https://ip.sb",
            "https://cip.cc",
        ],
        description="List of public IP lookup API endpoints",
    )


def get_settings(env_file: Optional[str] = None) -> Settings:
    if env_file:
        return Settings(_env_file=env_file)
    return Settings()
