from typing import Any, Dict, Optional, Tuple
import httpx
import logging

logger = logging.getLogger("update_ip.bark")


class BarkNotifier:
    def __init__(
        self,
        bark_key: Optional[str] = None,
        bark_server: str = "https://api.day.app",
        default_group: str = "IP-Monitor",
        default_icon: Optional[str] = "https://cdn-icons-png.flaticon.com/512/2920/2920244.png",
        default_sound: Optional[str] = None,
        default_level: str = "active",
        timeout: float = 10.0,
    ):
        self.bark_key = bark_key.strip() if bark_key else None
        self.bark_server = bark_server.rstrip("/")
        self.default_group = default_group
        self.default_icon = default_icon
        self.default_sound = default_sound
        self.default_level = default_level
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.bark_key)

    async def send(
        self,
        title: str,
        body: str,
        group: Optional[str] = None,
        icon: Optional[str] = None,
        sound: Optional[str] = None,
        level: Optional[str] = None,
        url: Optional[str] = None,
        badge: Optional[int] = None,
    ) -> Tuple[bool, str]:
        if not self.is_configured():
            msg = "Bark key is not configured. Notification skipped."
            logger.warning(msg)
            return False, msg

        endpoint = f"{self.bark_server}/push"
        payload: Dict[str, Any] = {
            "device_key": self.bark_key,
            "title": title,
            "body": body,
            "group": group or self.default_group,
            "level": level or self.default_level,
        }

        chosen_icon = icon or self.default_icon
        if chosen_icon:
            payload["icon"] = chosen_icon

        chosen_sound = sound or self.default_sound
        if chosen_sound:
            payload["sound"] = chosen_sound

        if url:
            payload["url"] = url
        if badge is not None:
            payload["badge"] = badge

        try:
            async with httpx.AsyncClient(verify=True) as client:
                logger.debug("Sending Bark push to %s with title: %r", endpoint, title)
                response = await client.post(
                    endpoint,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )

                if response.status_code == 404:
                    fallback_endpoint = f"{self.bark_server}/{self.bark_key}"
                    logger.debug("Bark /push endpoint unavailable; using legacy path endpoint on %s", self.bark_server)
                    response = await client.post(
                        fallback_endpoint,
                        json=payload,
                        timeout=self.timeout,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                    )

                response.raise_for_status()

                try:
                    resp_json = response.json()
                    code = resp_json.get("code")
                    message = resp_json.get("message", "OK")
                    if code == 200 or message == "success":
                        logger.info("Bark notification sent successfully: %s", title)
                        return True, f"Success: {message}"
                    logger.warning("Bark returned non-200 payload: %s", resp_json)
                    return False, f"Bark response error: code={code}, message={message}"
                except Exception:
                    logger.info("Bark notification sent with HTTP %s", response.status_code)
                    return True, f"HTTP {response.status_code}"

        except httpx.HTTPStatusError as e:
            err_msg = f"Bark HTTP error {e.response.status_code}: {e.response.text}"
            logger.error(err_msg)
            return False, err_msg
        except Exception as e:
            err_msg = f"Failed to send Bark notification: {e}"
            logger.error(err_msg)
            return False, err_msg
