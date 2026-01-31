import json
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ProductInfo


class UIStoreScraper(BaseScraper):
    """Scraper for store.ui.com products."""

    DOMAIN_PATTERN = re.compile(r"store\.ui\.com")

    def can_handle(self, url: str) -> bool:
        return bool(self.DOMAIN_PATTERN.search(url))

    async def scrape(self, url: str) -> ProductInfo:
        """Scrape product info from UI.com store page.

        UI.com pages include JSON-LD structured data with product information.
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"
                },
                follow_redirects=True,
                timeout=30.0,
            )
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Look for JSON-LD structured data
        json_ld = self._extract_json_ld(soup)
        if json_ld:
            return self._parse_json_ld(json_ld, url)

        # Fallback: try to parse page directly
        return self._parse_html(soup, url)

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict | None:
        """Extract JSON-LD product data from the page."""
        scripts = soup.find_all("script", type="application/ld+json")

        for script in scripts:
            try:
                data = json.loads(script.string)

                # Handle array of schemas
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") in ("Product", "ProductGroup"):
                            return item
                elif data.get("@type") in ("Product", "ProductGroup"):
                    return data

            except (json.JSONDecodeError, TypeError):
                continue

        return None

    def _parse_json_ld(self, data: dict, url: str) -> ProductInfo:
        """Parse product info from JSON-LD data."""
        name = data.get("name", "Unknown Product")

        # For ProductGroup, collect offers from variants
        offers = data.get("offers", {})
        variants = data.get("hasVariant", [])

        if not offers and variants:
            # Use the first available variant, or fall back to the first variant
            chosen = None
            for variant in variants:
                v_offers = variant.get("offers", {})
                if isinstance(v_offers, list):
                    v_offers = v_offers[0] if v_offers else {}
                if self._is_available(v_offers.get("availability", "")):
                    chosen = v_offers
                    break
            if chosen is None and variants:
                chosen = variants[0].get("offers", {})
                if isinstance(chosen, list):
                    chosen = chosen[0] if chosen else {}
            offers = chosen or {}

        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price = None
        price_val = offers.get("price")
        if not price_val:
            price_spec = offers.get("priceSpecification", {})
            if isinstance(price_spec, list):
                price_spec = price_spec[0] if price_spec else {}
            price_val = price_spec.get("price")
        if price_val is not None:
            try:
                price = float(price_val)
            except (ValueError, TypeError):
                pass

        currency = offers.get("priceCurrency")
        if not currency:
            price_spec = offers.get("priceSpecification", {})
            if isinstance(price_spec, list):
                price_spec = price_spec[0] if price_spec else {}
            currency = price_spec.get("priceCurrency", "USD")
        currency = currency or "USD"

        # Check availability — for ProductGroup, available if any variant is
        if variants:
            available = any(
                self._is_available(
                    (v.get("offers") if isinstance(v.get("offers"), dict) else
                     (v["offers"][0] if v.get("offers") else {})).get("availability", "")
                )
                for v in variants
            )
        else:
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
        """Determine if product is available based on schema.org availability."""
        availability_lower = availability.lower()

        # schema.org availability values that indicate in-stock
        in_stock_values = [
            "instock",
            "in_stock",
            "instoreonly",
            "limitedavailability",
            "onlineonly",
            "presale",
        ]

        for value in in_stock_values:
            if value in availability_lower:
                return True

        return False

    def _parse_html(self, soup: BeautifulSoup, url: str) -> ProductInfo:
        """Fallback HTML parsing when JSON-LD is not available."""
        # Try to find product name
        name = "Unknown Product"
        name_elem = soup.find("h1")
        if name_elem:
            name = name_elem.get_text(strip=True)

        # Try to find price
        price = None
        price_elem = soup.find(class_=re.compile(r"price", re.I))
        if price_elem:
            price_text = price_elem.get_text(strip=True)
            price_match = re.search(r"[\d,]+\.?\d*", price_text)
            if price_match:
                try:
                    price = float(price_match.group().replace(",", ""))
                except ValueError:
                    pass

        # Try to determine availability
        available = False
        # Look for add to cart button
        add_to_cart = soup.find(
            lambda tag: tag.name in ("button", "a") and
            "add to cart" in tag.get_text(strip=True).lower()
        )
        if add_to_cart and not add_to_cart.get("disabled"):
            available = True

        # Look for out of stock indicators
        out_of_stock = soup.find(
            string=re.compile(r"out of stock|sold out|unavailable", re.I)
        )
        if out_of_stock:
            available = False

        return ProductInfo(
            name=name,
            price=price,
            available=available,
            url=url,
        )
