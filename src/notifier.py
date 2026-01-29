import logging

import httpx

from .config import PushoverConfig
from .scrapers.base import ProductInfo

logger = logging.getLogger(__name__)

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"


class PushoverNotifier:
    """Send push notifications via Pushover API."""

    def __init__(self, config: PushoverConfig):
        self.config = config

    async def notify_available(self, product: ProductInfo) -> bool:
        """Send notification that a product is now available.

        Returns True if notification was sent successfully.
        """
        if not self.config.user_key or not self.config.api_token:
            logger.warning("Pushover credentials not configured, skipping notification")
            return False

        price_str = f"${product.price:.2f}" if product.price else "Price unknown"

        message = f"{product.name} is now available!\n\n{price_str}"

        payload = {
            "token": self.config.api_token,
            "user": self.config.user_key,
            "title": "Item Available!",
            "message": message,
            "url": product.url,
            "url_title": "View Product",
            "priority": 1,  # High priority
            "sound": "cashregister",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PUSHOVER_API_URL,
                    data=payload,
                    timeout=30.0,
                )
                response.raise_for_status()

            logger.info(f"Notification sent for: {product.name}")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Pushover API error: {e.response.status_code} - {e.response.text}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    async def send_test(self) -> bool:
        """Send a test notification to verify configuration."""
        if not self.config.user_key or not self.config.api_token:
            logger.error("Pushover credentials not configured")
            return False

        payload = {
            "token": self.config.api_token,
            "user": self.config.user_key,
            "title": "Price Checker Test",
            "message": "Test notification - your Price Checker is configured correctly!",
            "priority": 0,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    PUSHOVER_API_URL,
                    data=payload,
                    timeout=30.0,
                )
                response.raise_for_status()

            logger.info("Test notification sent successfully")
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Pushover API error: {e.response.status_code} - {e.response.text}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Failed to send test notification: {e}")
            return False
