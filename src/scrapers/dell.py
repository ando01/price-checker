import json
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ProductInfo


class DellScraper(BaseScraper):
    """Scraper for Dell product pages (servers and other products)."""

    DOMAIN_PATTERN = re.compile(r"dell\.com")

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

        # Fall back to HTML / meta tag parsing
        return self._parse_html(soup, url)

    def _extract_json_ld(self, soup: BeautifulSoup) -> dict | None:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
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
        name = data.get("name", "Unknown Product")

        offers = data.get("offers", {})
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
                price = float(str(price_val).replace(",", ""))
            except (ValueError, TypeError):
                pass

        currency = offers.get("priceCurrency", "USD") or "USD"

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
        # Product name: try og:title, then page title, then h1
        name = "Unknown Product"
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            name = og_title["content"].strip()
        else:
            title_tag = soup.find("title")
            if title_tag:
                # Dell titles are often "Product Name | Dell USA" – strip the suffix
                raw = title_tag.get_text(strip=True)
                name = re.sub(r"\s*[|\-–]\s*Dell.*$", "", raw).strip() or raw
            if not name or name == "Unknown Product":
                h1 = soup.find("h1")
                if h1:
                    name = h1.get_text(strip=True)

        # Price: try og:price:amount, then common Dell price selectors
        price = None
        og_price = soup.find("meta", property="og:price:amount")
        if og_price and og_price.get("content"):
            try:
                price = float(og_price["content"].replace(",", ""))
            except (ValueError, TypeError):
                pass

        if price is None:
            price_selectors = [
                "[data-testid='product-price']",
                ".pd-price",
                ".ps-price",
                ".product-price",
                "[class*='starting-price']",
                "[class*='price']",
            ]
            for selector in price_selectors:
                elem = soup.select_one(selector)
                if elem:
                    price_text = elem.get_text(strip=True)
                    match = re.search(r"[\d,]+\.?\d*", price_text)
                    if match:
                        try:
                            price = float(match.group().replace(",", ""))
                            break
                        except ValueError:
                            pass

        # Availability: look for configure/buy buttons or out-of-stock text
        available = False
        buy_btn = soup.find(
            lambda tag: tag.name in ("button", "a")
            and re.search(
                r"add to cart|configure|buy now|customize",
                tag.get_text(strip=True),
                re.I,
            )
            and not tag.get("disabled")
        )
        if buy_btn:
            available = True

        out_of_stock = soup.find(
            string=re.compile(r"out of stock|sold out|unavailable|discontinued", re.I)
        )
        if out_of_stock:
            available = False

        return ProductInfo(
            name=name,
            price=price,
            available=available,
            url=url,
        )
