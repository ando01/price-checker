import asyncio
import logging

from .config import Config
from .database import Database
from .notifier import PushoverNotifier
from .scrapers.amazon import AmazonScraper
from .scrapers.base import BaseScraper, ProductInfo
from .scrapers.ui_store import UIStoreScraper

logger = logging.getLogger(__name__)


class ProductChecker:
    """Check product availability and send notifications."""

    def __init__(self, config: Config, database: Database):
        self.config = config
        self.database = database
        self.notifier = PushoverNotifier(config.pushover)
        self.scrapers: list[BaseScraper] = [
            UIStoreScraper(),
            AmazonScraper(),
        ]

    def _get_scraper(self, url: str) -> BaseScraper | None:
        """Find a scraper that can handle the given URL."""
        for scraper in self.scrapers:
            if scraper.can_handle(url):
                return scraper
        return None

    async def check_product(self, url: str, name: str | None = None) -> ProductInfo | None:
        """Check a single product and update database."""
        scraper = self._get_scraper(url)
        if not scraper:
            logger.warning(f"No scraper found for URL: {url}")
            return None

        try:
            info = await scraper.scrape(url)
            logger.info(
                f"Checked {info.name}: "
                f"{'Available' if info.available else 'Unavailable'} "
                f"- ${info.price:.2f}" if info.price else f"Checked {info.name}"
            )
            return info

        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            return None

    async def check_all_products(self) -> None:
        """Check all configured products and send notifications for newly available items."""
        logger.info("Starting product check...")

        # Ensure all configured products are in the database
        for product_config in self.config.products:
            self.database.add_product(product_config.url, product_config.name)

        products = self.database.get_all_products()

        if not products:
            logger.warning("No products configured to check")
            return

        for product in products:
            info = await self.check_product(product.url, product.name)

            if info is None:
                continue

            previous_status = product.last_status
            current_status = "available" if info.available else "unavailable"

            # Update database
            self.database.update_product_status(
                product_id=product.id,
                status=current_status,
                price=info.price,
                name=info.name if not product.name else None,
            )

            # Send notification if item just became available
            if current_status == "available" and previous_status != "available":
                logger.info(f"Item became available: {info.name}")
                await self.notifier.notify_available(info)

            # Small delay between checks to be polite to servers
            await asyncio.sleep(1)

        logger.info("Product check complete")

    async def check_all_prices(self) -> None:
        """Check all products for price drops and send notifications."""
        logger.info("Starting price check...")

        products = self.database.get_all_products()

        if not products:
            logger.warning("No products configured to check")
            return

        for product in products:
            if product.last_price is None:
                continue

            info = await self.check_product(product.url, product.name)

            if info is None or info.price is None:
                continue

            old_price = product.last_price
            new_price = info.price

            # Update database with latest info
            current_status = "available" if info.available else "unavailable"
            self.database.update_product_status(
                product_id=product.id,
                status=current_status,
                price=new_price,
                name=info.name if not product.name else None,
            )

            # Notify on price drop only
            if new_price < old_price:
                logger.info(
                    f"Price drop for {product.name or product.url}: "
                    f"${old_price:.2f} → ${new_price:.2f}"
                )
                await self.notifier.notify_price_drop(product, old_price, new_price)

            await asyncio.sleep(1)

        logger.info("Price check complete")

    def run_check(self) -> None:
        """Synchronous wrapper for check_all_products (for APScheduler)."""
        asyncio.run(self.check_all_products())

    def run_price_check(self) -> None:
        """Synchronous wrapper for check_all_prices (for APScheduler)."""
        asyncio.run(self.check_all_prices())
