import json
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ProductInfo

logger = logging.getLogger(__name__)


@dataclass
class CSSSelectors:
    """Optional CSS selectors for custom extraction."""
    name: str | None = None
    price: str | None = None
    availability: str | None = None


class GenericScraper(BaseScraper):
    """Generic fallback scraper that works with most e-commerce sites.

    Tries multiple extraction strategies in order:
    1. JSON-LD structured data (schema.org Product)
    2. Open Graph / product meta tags
    3. Custom CSS selectors (if provided)
    4. Page title fallback
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }

    def can_handle(self, url: str) -> bool:
        """Always returns True — this is the catch-all fallback scraper."""
        return True

    async def scrape(self, url: str, selectors: CSSSelectors | None = None) -> ProductInfo:
        """Scrape product info using multiple strategies."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.HEADERS,
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Strategy 1: JSON-LD structured data
        json_ld = self._extract_json_ld(soup)
        if json_ld:
            info = self._parse_json_ld(json_ld, url)
            if info.name != "Unknown Product" or info.price is not None:
                logger.debug("Generic scraper: extracted via JSON-LD for %s", url)
                return info

        # Strategy 2: Open Graph / product meta tags
        info = self._parse_meta_tags(soup, url)
        if info.name != "Unknown Product" or info.price is not None:
            logger.debug("Generic scraper: extracted via meta tags for %s", url)
            # Try to enhance with CSS selectors if we're missing data
            if selectors and (info.price is None or info.name == "Unknown Product"):
                css_info = self._parse_css_selectors(soup, url, selectors)
                if info.name == "Unknown Product" and css_info.name != "Unknown Product":
                    info = ProductInfo(
                        name=css_info.name, price=info.price, available=info.available,
                        url=url, currency=info.currency,
                    )
                if info.price is None and css_info.price is not None:
                    info = ProductInfo(
                        name=info.name, price=css_info.price, available=info.available,
                        url=url, currency=info.currency,
                    )
            return info

        # Strategy 3: Custom CSS selectors
        if selectors:
            info = self._parse_css_selectors(soup, url, selectors)
            if info.name != "Unknown Product" or info.price is not None:
                logger.debug("Generic scraper: extracted via CSS selectors for %s", url)
                return info

        # Strategy 4: Best-effort fallback
        name = self._get_page_title(soup)
        logger.warning("Generic scraper: limited data extracted for %s", url)
        return ProductInfo(name=name, price=None, available=False, url=url)

    # --- JSON-LD ---

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict | None:
        """Find a Product JSON-LD block in the page."""
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                product = self._find_product_in_json_ld(data)
                if product:
                    return product
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _find_product_in_json_ld(self, data) -> dict | None:
        """Recursively find a Product type in JSON-LD data."""
        if isinstance(data, list):
            for item in data:
                result = self._find_product_in_json_ld(item)
                if result:
                    return result
        elif isinstance(data, dict):
            item_type = data.get("@type", "")
            if isinstance(item_type, list):
                types = item_type
            else:
                types = [item_type]
            if any(t in ("Product", "ProductGroup") for t in types):
                return data
            # Check @graph
            graph = data.get("@graph")
            if graph:
                return self._find_product_in_json_ld(graph)
        return None

    def _parse_json_ld(self, data: dict, url: str) -> ProductInfo:
        """Parse a schema.org Product JSON-LD object."""
        name = data.get("name", "Unknown Product")

        offers = data.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        # AggregateOffer — use lowPrice
        if offers.get("@type") == "AggregateOffer":
            price_val = offers.get("lowPrice") or offers.get("price")
        else:
            price_val = offers.get("price")

        if not price_val:
            price_spec = offers.get("priceSpecification", {})
            if isinstance(price_spec, list):
                price_spec = price_spec[0] if price_spec else {}
            price_val = price_spec.get("price")

        price = self._parse_price_value(price_val)

        currency = offers.get("priceCurrency", "USD") or "USD"

        availability = offers.get("availability", "")
        available = self._is_available(availability)

        return ProductInfo(
            name=name, price=price, available=available, url=url, currency=currency,
        )

    # --- Meta tags ---

    def _parse_meta_tags(self, soup: BeautifulSoup, url: str) -> ProductInfo:
        """Extract product info from Open Graph and other meta tags."""
        name = (
            self._get_meta(soup, "og:title")
            or self._get_meta(soup, "twitter:title")
            or self._get_page_title(soup)
        )

        price = self._parse_price_value(
            self._get_meta(soup, "product:price:amount")
            or self._get_meta(soup, "og:price:amount")
        )

        currency = (
            self._get_meta(soup, "product:price:currency")
            or self._get_meta(soup, "og:price:currency")
            or "USD"
        )

        availability_meta = (
            self._get_meta(soup, "product:availability")
            or self._get_meta(soup, "og:availability")
            or ""
        )
        available = self._is_available(availability_meta)

        return ProductInfo(
            name=name, price=price, available=available, url=url, currency=currency,
        )

    def _get_meta(self, soup: BeautifulSoup, prop: str) -> str | None:
        """Get content of a meta tag by property or name."""
        tag = soup.find("meta", attrs={"property": prop})
        if not tag:
            tag = soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    # --- CSS selectors ---

    def _parse_css_selectors(
        self, soup: BeautifulSoup, url: str, selectors: CSSSelectors,
    ) -> ProductInfo:
        """Extract product info using user-provided CSS selectors."""
        name = "Unknown Product"
        if selectors.name:
            elem = soup.select_one(selectors.name)
            if elem:
                name = elem.get_text(strip=True)

        price = None
        if selectors.price:
            elem = soup.select_one(selectors.price)
            if elem:
                price = self._parse_price_text(elem.get_text(strip=True))

        available = False
        if selectors.availability:
            elem = soup.select_one(selectors.availability)
            if elem:
                text = elem.get_text(strip=True).lower()
                available = self._is_available(text)
        else:
            # If no availability selector, assume available when we found a price
            available = price is not None

        return ProductInfo(name=name, price=price, available=available, url=url)

    # --- Helpers ---

    def _get_page_title(self, soup: BeautifulSoup) -> str:
        """Get the page <title> as a fallback product name."""
        title = soup.find("title")
        if title:
            text = title.get_text(strip=True)
            # Strip common suffixes like " | SiteName" or " - SiteName"
            for sep in [" | ", " - ", " — ", " – "]:
                if sep in text:
                    text = text.split(sep)[0].strip()
                    break
            return text
        return "Unknown Product"

    def _is_available(self, text: str) -> bool:
        """Check if an availability string indicates in-stock."""
        text_lower = text.lower()
        in_stock_values = [
            "instock", "in_stock", "in stock",
            "instoreonly", "onlineonly",
            "limitedavailability", "presale",
            "available",
        ]
        out_of_stock_values = [
            "outofstock", "out_of_stock", "out of stock",
            "unavailable", "sold out", "soldout",
            "discontinued",
        ]
        # Check out-of-stock first (more specific)
        if any(v in text_lower for v in out_of_stock_values):
            return False
        return any(v in text_lower for v in in_stock_values)

    def _parse_price_value(self, value) -> float | None:
        """Parse a price from a structured value (JSON-LD, meta tag)."""
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return self._parse_price_text(str(value))

    def _parse_price_text(self, text: str) -> float | None:
        """Extract a numeric price from text like '$1,299.99'."""
        if not text:
            return None
        match = re.search(r"[\d,]+\.?\d*", text.replace(" ", ""))
        if match:
            try:
                return float(match.group().replace(",", ""))
            except ValueError:
                pass
        return None
