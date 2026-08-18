import ipaddress
import re
from typing import List, Optional, Tuple
import httpx
import logging

logger = logging.getLogger("update_ip.checker")

# Regular expression to extract IPv4 or IPv6 address from text
IPV4_REGEX = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
IPV6_REGEX = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|\b(?:[0-9a-fA-F]{1,4}:)*:[0-9a-fA-F]{1,4}\b")


def extract_and_validate_ip(text: str) -> Optional[str]:
    """Extract and validate the first valid IPv4 or IPv6 address found in text."""
    text = text.strip()
    # First check if the full text is a direct IP
    try:
        ip_obj = ipaddress.ip_address(text)
        return str(ip_obj)
    except ValueError:
        pass

    # Search for IPv4 match
    v4_matches = IPV4_REGEX.findall(text)
    for candidate in v4_matches:
        try:
            ip_obj = ipaddress.ip_address(candidate)
            return str(ip_obj)
        except ValueError:
            continue

    # Search for IPv6 match
    v6_matches = IPV6_REGEX.findall(text)
    for candidate in v6_matches:
        try:
            ip_obj = ipaddress.ip_address(candidate)
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
    ):
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

    async def _fetch_from_provider(self, client: httpx.AsyncClient, provider: str) -> str:
        headers = {
            "User-Agent": "curl/8.7.1 update-ip-monitor/1.0",
            "Accept": "text/plain, application/json, */*",
        }
        response = await client.get(provider, headers=headers, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        # Try parsing JSON if applicable
        if "application/json" in content_type or raw_text.strip().startswith("{"):
            try:
                data = response.json()
                if isinstance(data, dict):
                    # Common keys: "ip", "origin", "query"
                    for key in ["ip", "origin", "query", "addr"]:
                        if key in data and isinstance(data[key], str):
                            extracted = extract_and_validate_ip(data[key])
                            if extracted:
                                return extracted
            except Exception:
                pass

        # Fallback to text parsing
        extracted = extract_and_validate_ip(raw_text)
        if not extracted:
            raise ValueError(f"No valid IP address found in response from {provider}: {raw_text[:100]}")
        return extracted

    async def get_current_ip(self) -> Tuple[str, str]:
        """
        Iterate through providers until a valid IP is retrieved.
        Returns:
            Tuple[str, str]: (IP Address, Successful Provider URL)
        Raises:
            RuntimeError: If all providers fail.
        """
        errors = []
        async with httpx.AsyncClient(verify=True) as client:
            for provider in self.providers:
                for attempt in range(1, self.max_retries_per_provider + 1):
                    try:
                        logger.debug(f"Fetching IP from {provider} (attempt {attempt}/{self.max_retries_per_provider})...")
                        ip = await self._fetch_from_provider(client, provider)
                        logger.debug(f"Successfully retrieved IP {ip} from {provider}")
                        return ip, provider
                    except Exception as e:
                        logger.warning(f"Provider {provider} attempt {attempt} failed: {e}")
                        errors.append(f"{provider} (attempt {attempt}): {e}")

        error_summary = "\n  - " + "\n  - ".join(errors)
        raise RuntimeError(f"All IP providers failed:\n{error_summary}")

    async def test_all_providers(self) -> List[dict]:
        """Test each provider individually and return diagnostics."""
        results = []
        async with httpx.AsyncClient(verify=True) as client:
            for provider in self.providers:
                try:
                    ip = await self._fetch_from_provider(client, provider)
                    results.append({
                        "provider": provider,
                        "success": True,
                        "ip": ip,
                        "error": None,
                    })
                except Exception as e:
                    results.append({
                        "provider": provider,
                        "success": False,
                        "ip": None,
                        "error": str(e),
                    })
        return results
