import asyncio
import ipaddress
import logging
import re
from typing import Literal

import httpx

logger = logging.getLogger("update_ip.checker")

IPVersion = Literal["4", "6", "any"]
IP_CANDIDATE_REGEX = re.compile(r"[0-9A-Fa-f:.]+")


def _matches_version(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, version: IPVersion) -> bool:
    return version == "any" or ip.version == int(version)


def extract_and_validate_ip(text: str, version: IPVersion = "any") -> str | None:
    """Return the first valid IP matching the requested address family."""
    text = text.strip()
    candidates = [text, *IP_CANDIDATE_REGEX.findall(text)]
    for candidate in candidates:
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if _matches_version(ip, version):
            return str(ip)
    return None


class IPChecker:
    def __init__(
        self,
        providers: list[str] | None = None,
        timeout: float = 10.0,
        max_retries_per_provider: int = 2,
        ip_version: IPVersion = "4",
    ):
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")
        if max_retries_per_provider < 1:
            raise ValueError("max_retries_per_provider must be at least 1")
        if ip_version not in ("4", "6", "any"):
            raise ValueError("ip_version must be '4', '6', or 'any'")

        self.providers = providers or [
            "https://api64.ipify.org?format=json",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
            "https://ident.me",
            "https://api.ipify.org",
            "https://ip.sb",
            "https://httpbin.org/ip",
        ]
        self.timeout = timeout
        self.max_retries_per_provider = max_retries_per_provider
        self.ip_version = ip_version

    async def _fetch_from_provider(self, client: httpx.AsyncClient, provider: str) -> str:
        response = await client.get(
            provider,
            headers={
                "User-Agent": "curl/8.7.1 update-ip-monitor/1.0",
                "Accept": "text/plain, application/json, */*",
            },
            timeout=self.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        raw_text = response.text

        if "application/json" in response.headers.get("content-type", "") or raw_text.lstrip().startswith("{"):
            try:
                data = response.json()
                if isinstance(data, dict):
                    for key in ("ip", "origin", "query", "addr"):
                        value = data.get(key)
                        if isinstance(value, str) and (ip := extract_and_validate_ip(value, self.ip_version)):
                            return ip
            except ValueError:
                pass

        if ip := extract_and_validate_ip(raw_text, self.ip_version):
            return ip
        family = self.ip_version if self.ip_version != "any" else "4/6"
        raise ValueError(f"No valid IPv{family} address found in response from {provider}: {raw_text[:100]}")

    async def get_current_ip(self) -> tuple[str, str]:
        """Return the first valid IP and provider URL."""
        errors: list[str] = []
        async with httpx.AsyncClient(verify=True) as client:
            for provider in self.providers:
                for attempt in range(1, self.max_retries_per_provider + 1):
                    try:
                        logger.debug(
                            "Fetching IP from %s (attempt %s/%s)...",
                            provider,
                            attempt,
                            self.max_retries_per_provider,
                        )
                        return await self._fetch_from_provider(client, provider), provider
                    except Exception as exc:
                        logger.warning("Provider %s attempt %s failed: %s", provider, attempt, exc)
                        errors.append(f"{provider} (attempt {attempt}): {exc}")
                        if attempt < self.max_retries_per_provider:
                            await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 2.0))

        raise RuntimeError("All IP providers failed:\n  - " + "\n  - ".join(errors))

    async def test_all_providers(self) -> list[dict]:
        """Test each provider individually and return diagnostics."""
        results = []
        async with httpx.AsyncClient(verify=True) as client:
            for provider in self.providers:
                try:
                    ip = await self._fetch_from_provider(client, provider)
                    results.append({"provider": provider, "success": True, "ip": ip, "error": None})
                except Exception as exc:
                    results.append({"provider": provider, "success": False, "ip": None, "error": str(exc)})
        return results
