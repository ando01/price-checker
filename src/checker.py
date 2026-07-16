import asyncio
import logging
from datetime import datetime

from .config import Config
from .database import Database, Product
from .notifier import PushoverNotifier
from .scrapers.amazon import AmazonScraper
from .scrapers.base import BaseScraper, ProductInfo
from .scrapers.dell import DellScraper
from .scrapers.generic import CSSSelectors, GenericScraper
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
            DellScraper(),
        ]
        self.generic_scraper = GenericScraper()

    def _get_scraper(self, url: str) -> BaseScraper | None:
        """Find a scraper that can handle the given URL."""
        for scraper in self.scrapers:
            if scraper.can_handle(url):
                return scraper
        return None

    async def check_product(
        self, url: str, name: str | None = None, product: Product | None = None,
    ) -> ProductInfo | None:
        """Check a single product and update database."""
        scraper = self._get_scraper(url)

        try:
            if scraper:
                info = await scraper.scrape(url)
            else:
                # Use generic scraper with optional CSS selectors from DB
                selectors = None
                if product and (product.css_name or product.css_price or product.css_availability):
                    selectors = CSSSelectors(
                        name=product.css_name,
                        price=product.css_price,
                        availability=product.css_availability,
                    )
                info = await self.generic_scraper.scrape(url, selectors=selectors)

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
            if not product.check_availability:
                continue

            info = await self.check_product(product.url, product.name, product=product)

            if info is None:
                continue

            previous_status = product.last_status
            current_status = "available" if info.available else "unavailable"

            # Update database (preserve existing price if scraper didn't find one)
            self.database.update_product_status(
                product_id=product.id,
                status=current_status,
                price=info.price if info.price is not None else product.last_price,
                name=info.name if not product.name else None,
            )

            # Send notification if item just became available
            if product.notify and current_status == "available" and previous_status != "available":
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
            if not product.check_price:
                continue

            if product.last_price is None:
                continue

            info = await self.check_product(product.url, product.name, product=product)

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

            # Update lowest price seen
            if new_price is not None and (
                product.lowest_price is None or new_price < product.lowest_price
            ):
                self.database.update_product_lowest_price(product.id, new_price, datetime.now())

            # Notify on price drop only (no target set)
            if product.notify and new_price < old_price and product.target_price is None:
                logger.info(
                    f"Price drop for {product.name or product.url}: "
                    f"${old_price:.2f} → ${new_price:.2f}"
                )
                await self.notifier.notify_price_drop(product, old_price, new_price)

            # Notify when item is available AND price is at or below target
            if (
                product.notify
                and product.target_price is not None
                and info.available
                and new_price <= product.target_price
            ):
                logger.info(
                    f"Target price reached for {product.name or product.url}: "
                    f"${new_price:.2f} ≤ ${product.target_price:.2f}"
                )
                await self.notifier.notify_target_price_reached(
                    product, product.target_price, new_price
                )

            await asyncio.sleep(1)

        logger.info("Price check complete")

    async def _update_lowest_price(
        self, product: Product, new_price: float, now: datetime | None = None
    ) -> None:
        """Update the product's lowest price if the new price is lower."""
        if new_price is not None and (
            product.lowest_price is None or new_price < product.lowest_price
        ):
            self.database.update_product_lowest_price(
                product.id, new_price, now or datetime.now()
            )
            logger.info(
                f"New lowest price for {product.name or product.url}: "
                f"${new_price:.2f}"
            )

    async def check_one(self, product_id: int) -> ProductInfo | None:
        """Check a single product by ID, update the DB, and fire notifications."""
        product = self.database.get_product_by_id(product_id)
        if product is None or (not product.check_availability and not product.check_price):
            return None

        info = await self.check_product(product.url, product.name, product=product)
        if info is None:
            return None

        previous_status = product.last_status
        old_price = product.last_price
        current_status = "available" if info.available else "unavailable"
        new_price = info.price if info.price is not None else old_price

        self.database.update_product_status(
            product_id=product.id,
            status=current_status,
            price=new_price,
            name=info.name if not product.name else None,
        )

        if product.notify and product.check_availability and current_status == "available" and previous_status != "available":
            logger.info(f"Item became available: {info.name}")
            await self.notifier.notify_available(info)

        if product.notify and product.check_price and info.price is not None and old_price is not None:
            # Notify on price drop only (no target set)
            if info.price < old_price and product.target_price is None:
                logger.info(
                    f"Price drop for {product.name or product.url}: "
                    f"${old_price:.2f} → ${info.price:.2f}"
                )
                await self.notifier.notify_price_drop(product, old_price, info.price)

            # Notify when item is available AND price is at or below target
            if (
                product.target_price is not None
                and info.available
                and info.price <= product.target_price
            ):
                logger.info(
                    f"Target price reached for {product.name or product.url}: "
                    f"${info.price:.2f} ≤ ${product.target_price:.2f}"
                )
                await self.notifier.notify_target_price_reached(
                    product, product.target_price, info.price
                )

        # Update lowest price seen
        await self._update_lowest_price(product, new_price)

        return info

    def run_check(self) -> None:
        """Synchronous wrapper for check_all_products (for APScheduler)."""
        asyncio.run(self.check_all_products())

    def run_price_check(self) -> None:
        """Synchronous wrapper for check_all_prices (for APScheduler)."""
        asyncio.run(self.check_all_prices())
