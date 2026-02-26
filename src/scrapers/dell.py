import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ProductInfo

logger = logging.getLogger(__name__)


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
        # Omit 'br' (Brotli) — brotlicffi is not installed, so httpx cannot
        # decode it. Manually advertising br causes the server to send Brotli-
        # compressed bytes that httpx silently passes through undecoded,
        # resulting in BeautifulSoup receiving binary garbage.
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
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

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Log a snippet of the response to help diagnose parsing failures
        logger.debug("Dell response first 1000 chars: %s", html[:1000])

        # 1. Try JSON-LD structured data
        json_ld = self._extract_json_ld(soup)
        if json_ld:
            logger.debug("Dell: found JSON-LD product data")
            return self._parse_json_ld(json_ld, url)

        # 2. Try Next.js __NEXT_DATA__ (Dell uses Next.js)
        info = self._try_next_data(soup, url)
        if info:
            return info

        # 3. Try any inline script tag that looks like a product data blob
        info = self._try_inline_scripts(soup, url)
        if info:
            return info

        # 4. Fall back to HTML / meta tag parsing
        result = self._parse_html(soup, url)
        if result.name == "Unknown Product":
            title_text = soup.find("title")
            title_text = title_text.get_text(strip=True) if title_text else None
            og_title = soup.find("meta", property="og:title")
            og_title = og_title.get("content") if og_title else None
            script_count = len(soup.find_all("script"))
            logger.warning(
                "Dell scraper could not extract data from %s — "
                "page likely requires JS. title=%r og:title=%r scripts=%d html_len=%d",
                url, title_text, og_title, script_count, len(html),
            )
        return result

    # ------------------------------------------------------------------ #
    # JSON-LD                                                              #
    # ------------------------------------------------------------------ #

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

        return ProductInfo(name=name, price=price, available=available, url=url, currency=currency)

    # ------------------------------------------------------------------ #
    # Next.js __NEXT_DATA__                                                #
    # ------------------------------------------------------------------ #

    def _try_next_data(self, soup: BeautifulSoup, url: str) -> ProductInfo | None:
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            logger.info("Dell: no __NEXT_DATA__ script tag found in page")
            return None

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return None

        logger.info("Dell: __NEXT_DATA__ found, top-level keys: %s", list(data.keys()))

        # Walk the tree looking for product data
        page_props = data.get("props", {}).get("pageProps", {})
        logger.info("Dell: __NEXT_DATA__ pageProps keys: %s", list(page_props.keys()))

        # Try common paths Dell might use
        product = (
            page_props.get("product")
            or page_props.get("productDetails")
            or page_props.get("productData")
            or page_props.get("initialData", {}).get("product")
            or page_props.get("pdpData", {}).get("product")
            or self._deep_find(page_props, ("name", "price"))
        )

        if not product or not isinstance(product, dict):
            logger.debug("Dell: could not find product node in __NEXT_DATA__")
            return None

        name = (
            product.get("name")
            or product.get("title")
            or product.get("productName")
        )
        if not name:
            return None

        price = self._extract_price_from_dict(product)
        available = self._extract_availability_from_dict(product)

        logger.debug("Dell __NEXT_DATA__ parsed: name=%r price=%r available=%r", name, price, available)
        return ProductInfo(name=name, price=price, available=available, url=url)

    # ------------------------------------------------------------------ #
    # Inline script heuristic                                              #
    # ------------------------------------------------------------------ #

    def _try_inline_scripts(self, soup: BeautifulSoup, url: str) -> ProductInfo | None:
        """Search all inline <script> tags for embedded product JSON blobs."""
        patterns = [
            # window.digitalData / Adobe DTM style
            re.compile(r'window\.__(?:INITIAL_STATE|PRELOADED_STATE|STATE|DATA)__\s*=\s*(\{.+?\});', re.S),
            re.compile(r'"productName"\s*:\s*"([^"]+)"'),
        ]

        for script in soup.find_all("script"):
            text = script.string or ""
            if not text:
                continue

            # Try to parse full JSON assignments
            for pat in patterns[:1]:
                match = pat.search(text)
                if match:
                    try:
                        obj = json.loads(match.group(1))
                        product = self._deep_find(obj, ("name", "price"))
                        if product and product.get("name"):
                            name = product["name"]
                            price = self._extract_price_from_dict(product)
                            available = self._extract_availability_from_dict(product)
                            logger.debug("Dell inline script parsed: name=%r", name)
                            return ProductInfo(name=name, price=price, available=available, url=url)
                    except (json.JSONDecodeError, TypeError):
                        continue

            # Cheap: just look for a productName string in the script
            m = re.search(r'"(?:productName|product_name|name)"\s*:\s*"(PowerEdge[^"]+)"', text)
            if m:
                name = m.group(1)
                price_m = re.search(r'"(?:price|salePrice|finalPrice|unitPrice)"\s*:\s*([\d.]+)', text)
                price = float(price_m.group(1)) if price_m else None
                logger.debug("Dell inline script regex parsed: name=%r price=%r", name, price)
                return ProductInfo(name=name, price=price, available=True, url=url)

        return None

    # ------------------------------------------------------------------ #
    # HTML / meta fallback                                                 #
    # ------------------------------------------------------------------ #

    def _parse_html(self, soup: BeautifulSoup, url: str) -> ProductInfo:
        name = "Unknown Product"
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            name = og_title["content"].strip()
        else:
            title_tag = soup.find("title")
            if title_tag:
                raw = title_tag.get_text(strip=True)
                # Strip "| Dell USA" suffix
                cleaned = re.sub(r"\s*[|\-–]\s*Dell.*$", "", raw).strip()
                name = cleaned if cleaned else raw
            if not name or name == "Unknown Product":
                h1 = soup.find("h1")
                if h1:
                    name = h1.get_text(strip=True)

        price = None
        og_price = soup.find("meta", property="og:price:amount")
        if og_price and og_price.get("content"):
            try:
                price = float(og_price["content"].replace(",", ""))
            except (ValueError, TypeError):
                pass

        if price is None:
            for selector in [
                "[data-testid='product-price']",
                ".pd-price",
                ".ps-price",
                ".product-price",
                "[class*='starting-price']",
                "[class*='price']",
            ]:
                elem = soup.select_one(selector)
                if elem:
                    m = re.search(r"[\d,]+\.?\d*", elem.get_text(strip=True))
                    if m:
                        try:
                            price = float(m.group().replace(",", ""))
                            break
                        except ValueError:
                            pass

        available = False
        buy_btn = soup.find(
            lambda tag: tag.name in ("button", "a")
            and re.search(r"add to cart|configure|buy now|customize", tag.get_text(strip=True), re.I)
            and not tag.get("disabled")
        )
        if buy_btn:
            available = True
        if soup.find(string=re.compile(r"out of stock|sold out|unavailable|discontinued", re.I)):
            available = False

        return ProductInfo(name=name, price=price, available=available, url=url)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _is_available(self, availability: str) -> bool:
        low = availability.lower()
        return any(v in low for v in ["instock", "in_stock", "instoreonly", "limitedavailability", "onlineonly", "presale"])

    def _extract_price_from_dict(self, d: dict) -> float | None:
        for key in ("finalPrice", "salePrice", "price", "unitPrice", "listPrice", "startingPrice"):
            val = d.get(key)
            if val is not None:
                try:
                    return float(str(val).replace(",", "").replace("$", ""))
                except (ValueError, TypeError):
                    pass
        # Try nested pricing dict
        for key in ("pricing", "priceInfo", "priceDetails"):
            sub = d.get(key)
            if isinstance(sub, dict):
                result = self._extract_price_from_dict(sub)
                if result is not None:
                    return result
        return None

    def _extract_availability_from_dict(self, d: dict) -> bool:
        for key in ("availability", "stockStatus", "inventoryStatus", "inStock", "isAvailable"):
            val = d.get(key)
            if val is None:
                continue
            if isinstance(val, bool):
                return val
            return self._is_available(str(val))
        return False

    def _deep_find(self, obj, required_keys: tuple, _depth: int = 0) -> dict | None:
        """Recursively search a dict tree for a node that has all required_keys."""
        if _depth > 6:
            return None
        if isinstance(obj, dict):
            if all(k in obj for k in required_keys):
                return obj
            for v in obj.values():
                result = self._deep_find(v, required_keys, _depth + 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj[:5]:  # limit list scanning
                result = self._deep_find(item, required_keys, _depth + 1)
                if result:
                    return result
        return None
