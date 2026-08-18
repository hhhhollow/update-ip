import asyncio
import ipaddress
import logging
import re
from typing import List, Literal, Optional, Tuple

import httpx

logger = logging.getLogger("update_ip.checker")

IPV4_REGEX = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
IPV6_REGEX = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|\b(?:[0-9a-fA-F]{1,4}:)*:[0-9a-fA-F]{1,4}\b")
IPVersion = Literal["4", "6", "any"]


def _matches_version(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address, version: IPVersion) -> bool:
    return version == "any" or ip_obj.version == int(version)


def extract_and_validate_ip(text: str, version: IPVersion = "any") -> Optional[str]:
    """Extract and validate the first IP address matching the requested version."""
    text = text.strip()

    try:
        ip_obj = ipaddress.ip_address(text)
        return str(ip_obj) if _matches_version(ip_obj, version) else None
    except ValueError:
        pass

    for candidate in IPV4_REGEX.findall(text):
        try:
            ip_obj = ipaddress.ip_address(candidate)
            if _matches_version(ip_obj, version):
                return str(ip_obj)
        except ValueError:
            continue

    for candidate in IPV6_REGEX.findall(text):
        try:
            ip_obj = ipaddress.ip_address(candidate)
            if _matches_version(ip_obj, version):
                return str(ip_obj)
        except ValueError:
            continue

    return None


class IPChecker:
    def __init__(
        self,
        providers: Optional[List[str]] = None,
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
        headers = {
            "User-Agent": "curl/8.7.1 update-ip-monitor/1.0",
            "Accept": "text/plain, application/json, */*",
        }
        response = await client.get(provider, headers=headers, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        if "application/json" in content_type or raw_text.strip().startswith("{"):
            try:
                data = response.json()
                if isinstance(data, dict):
                    for key in ["ip", "origin", "query", "addr"]:
                        if key in data and isinstance(data[key], str):
                            extracted = extract_and_validate_ip(data[key], self.ip_version)
                            if extracted:
                                return extracted
            except Exception:
                pass

        extracted = extract_and_validate_ip(raw_text, self.ip_version)
        if not extracted:
            raise ValueError(
                f"No valid IPv{self.ip_version if self.ip_version != 'any' else '4/6'} address "
                f"found in response from {provider}: {raw_text[:100]}"
            )
        return extracted

    async def get_current_ip(self) -> Tuple[str, str]:
        """Return the first valid IP from the configured providers and its provider URL."""
        errors = []
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
                        ip = await self._fetch_from_provider(client, provider)
                        logger.debug("Successfully retrieved IP %s from %s", ip, provider)
                        return ip, provider
                    except Exception as e:
                        logger.warning("Provider %s attempt %s failed: %s", provider, attempt, e)
                        errors.append(f"{provider} (attempt {attempt}): {e}")
                        if attempt < self.max_retries_per_provider:
                            await asyncio.sleep(min(0.5 * (2 ** (attempt - 1)), 2.0))

        error_summary = "\n  - " + "\n  - ".join(errors)
        raise RuntimeError(f"All IP providers failed:\n{error_summary}")

    async def test_all_providers(self) -> List[dict]:
        """Test each provider individually and return diagnostics."""
        results = []
        async with httpx.AsyncClient(verify=True) as client:
            for provider in self.providers:
                try:
                    ip = await self._fetch_from_provider(client, provider)
                    results.append({"provider": provider, "success": True, "ip": ip, "error": None})
                except Exception as e:
                    results.append({"provider": provider, "success": False, "ip": None, "error": str(e)})
        return results
