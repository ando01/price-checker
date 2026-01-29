from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProductInfo:
    """Information scraped from a product page."""
    name: str
    price: float | None
    available: bool
    url: str
    currency: str = "USD"


class BaseScraper(ABC):
    """Base class for product scrapers."""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        pass

    @abstractmethod
    async def scrape(self, url: str) -> ProductInfo:
        """Scrape product information from the given URL."""
        pass
