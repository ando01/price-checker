import json
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ProductInfo


class AmazonScraper(BaseScraper):
    """Scraper for Amazon product pages."""

    DOMAIN_PATTERN = re.compile(r"amazon\.(com|co\.uk|ca|de|fr|it|es|co\.jp|com\.au)")

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
        "Accept-Encoding": "gzip, deflate, br",
    }

    def can_handle(self, url: str) -> bool:
        return bool(self.DOMAIN_PATTERN.search(url))

    async def scrape(self, url: str) -> ProductInfo:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self.HEADERS,
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Try JSON-LD structured data first
        json_ld = self._extract_json_ld(soup)
        if json_ld:
            return self._parse_json_ld(json_ld, url)

        # Fallback to HTML parsing
        return self._parse_html(soup, url)

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict | None:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif data.get("@type") == "Product":
                    return data
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _parse_json_ld(self, data: dict, url: str) -> ProductInfo:
        name = data.get("name", "Unknown Product")

        offers = data.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = None
        price_val = offers.get("price")
        if price_val:
            try:
                price = float(price_val)
            except (ValueError, TypeError):
                pass

        currency = offers.get("priceCurrency", "USD")

        availability = offers.get("availability", "")
        available = self._is_available(availability)

        return ProductInfo(
            name=name,
            price=price,
            available=available,
            url=url,
            currency=currency,
        )

    def _is_available(self, availability: str) -> bool:
        availability_lower = availability.lower()
        in_stock_values = [
            "instock",
            "in_stock",
            "instoreonly",
            "limitedavailability",
            "onlineonly",
            "presale",
        ]
        return any(v in availability_lower for v in in_stock_values)

    def _parse_html(self, soup: BeautifulSoup, url: str) -> ProductInfo:
        # Product title
        name = "Unknown Product"
        title_elem = soup.find(id="productTitle")
        if title_elem:
            name = title_elem.get_text(strip=True)

        # Price — Amazon uses .a-price .a-offscreen for the displayed price
        price = None
        price_elem = soup.select_one(".a-price .a-offscreen")
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            match = re.search(r"[\d,]+\.?\d*", price_text)
            if match:
                try:
                    price = float(match.group().replace(",", ""))
                except ValueError:
                    pass

        # Availability
        available = False
        avail_elem = soup.find(id="availability")
        if avail_elem:
            avail_text = avail_elem.get_text(strip=True).lower()
            if "in stock" in avail_text:
                available = True
            elif "unavailable" in avail_text or "out of stock" in avail_text:
                available = False
        else:
            # Fallback: check for Add to Cart button
            add_btn = soup.find(id="add-to-cart-button")
            if add_btn:
                available = True

        return ProductInfo(
            name=name,
            price=price,
            available=available,
            url=url,
        )
