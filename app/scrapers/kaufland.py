"""Kaufland Bulgaria web scraper.

Scrapes product listings from https://www.kaufland.bg/products/
with pagination support (up to 10 pages).

**New dependencies required (not yet in pyproject.toml):**
- beautifulsoup4 (HTML parsing)
- lxml (fast HTML parser backend)

httpx is already available in dev dependencies.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.kaufland.bg/products/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_PAGES = 10
_TIMEOUT_SECONDS = 30


class KauflandScraper(BaseScraper):
    """Scraper for Kaufland Bulgaria product listings.

    Fetches product pages from the Kaufland Bulgaria website,
    parses product tiles for name, price, unit, category, and image,
    and normalises them into ``ScrapedItem`` instances.
    """

    store_slug: ClassVar[str] = "kaufland"

    async def fetch(self) -> list[dict]:
        """Fetch product listing pages from Kaufland Bulgaria.

        Makes async HTTP GET requests starting from the base products URL,
        following pagination links up to a maximum of ``_MAX_PAGES`` pages.
        Stops early if a non-200 response is received or no next-page link
        is found.

        Returns:
            A list of dicts, each with keys ``"html"`` (page source) and
            ``"page"`` (1-based page number).
        """
        import httpx

        pages: list[dict] = []
        url: str | None = _BASE_URL

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            for page_num in range(1, _MAX_PAGES + 1):
                if url is None:
                    break

                try:
                    response = await client.get(url)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "HTTP error fetching page %d (%s): %s",
                        page_num,
                        url,
                        exc,
                    )
                    break

                if response.status_code != 200:
                    logger.warning(
                        "Non-200 status %d on page %d (%s) — stopping pagination",
                        response.status_code,
                        page_num,
                        url,
                    )
                    break

                pages.append({"html": response.text, "page": page_num})
                url = self._extract_next_page_url(response.text)

        return pages

    def parse(self, raw: list[dict]) -> list[ScrapedItem]:
        """Parse raw page HTML into a list of ``ScrapedItem`` objects.

        Each entry in *raw* is expected to be a dict with keys ``"html"``
        (the full page HTML string) and ``"page"`` (the 1-based page number).

        Args:
            raw: Output of :meth:`fetch` — a list of page dicts.

        Returns:
            A flat list of ``ScrapedItem`` instances extracted from all pages.
        """
        items: list[ScrapedItem] = []

        for page_data in raw:
            html = page_data.get("html", "")
            page_num = page_data.get("page", 0)
            soup = BeautifulSoup(html, "lxml")

            product_tiles = soup.find_all("div", class_="product-tile")
            for tile in product_tiles:
                item = self._parse_tile(tile, page_num)
                if item is not None:
                    items.append(item)

        return items

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_tile(self, tile: Tag, page_num: int) -> ScrapedItem | None:
        """Extract a single product from a product-tile element.

        Args:
            tile: A ``<div class="product-tile">`` BeautifulSoup Tag.
            page_num: The page this tile came from (for raw metadata).

        Returns:
            A ``ScrapedItem`` or ``None`` if required fields are missing.
        """
        name = self._extract_name(tile)
        if not name:
            logger.debug("Skipping tile on page %d — no product name found", page_num)
            return None

        price = self._extract_price(tile)
        if price is None:
            logger.debug(
                "Skipping tile '%s' on page %d — no valid price", name, page_num
            )
            return None

        unit = self._extract_unit(tile)
        category = self._extract_category(tile)
        image_url = self._extract_image_url(tile)

        return ScrapedItem(
            name=name,
            price=price,
            currency="BGN",
            unit=unit,
            image_url=image_url,
            source="web",
            raw={
                "page": page_num,
                "category_hint": category,
                "raw_html": str(tile)[:500],
            },
        )

    @staticmethod
    def _extract_name(tile: Tag) -> str | None:
        """Extract product name from the tile.

        Args:
            tile: A product-tile Tag.

        Returns:
            The product name string, or ``None`` if not found.
        """
        title_tag = tile.find("h3", class_="product-title")
        if title_tag is None:
            return None
        text = title_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_price(tile: Tag) -> Decimal | None:
        """Extract and parse the product price from the tile.

        Strips the Bulgarian Lev suffix (``лв.`` / ``лв``), removes
        whitespace and commas, then converts to ``Decimal``.

        Args:
            tile: A product-tile Tag.

        Returns:
            The price as a ``Decimal``, or ``None`` if parsing fails.
        """
        price_tag = tile.find("span", class_="price")
        if price_tag is None:
            return None

        raw_price = price_tag.get_text(strip=True)
        # Remove currency suffix and whitespace
        cleaned = (
            raw_price.replace("лв.", "")
            .replace("лв", "")
            .replace(",", ".")
            .replace(" ", "")
            .strip()
        )
        if not cleaned:
            return None

        try:
            return Decimal(cleaned)
        except InvalidOperation:
            logger.debug("Could not parse price string: %r", raw_price)
            return None

    @staticmethod
    def _extract_unit(tile: Tag) -> str | None:
        """Extract the unit descriptor (e.g. kg, l, бр) from the tile.

        Args:
            tile: A product-tile Tag.

        Returns:
            The unit string, or ``None`` if not found.
        """
        unit_tag = tile.find("span", class_="product-unit")
        if unit_tag is None:
            return None
        text = unit_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_category(tile: Tag) -> str | None:
        """Extract a category hint from the tile's data attribute or label.

        Args:
            tile: A product-tile Tag.

        Returns:
            A category string, or ``None`` if not present.
        """
        # Try data attribute first
        category = tile.get("data-category")
        if category:
            return str(category).strip()

        # Fall back to a category label element
        cat_tag = tile.find("span", class_="product-category")
        if cat_tag is not None:
            text = cat_tag.get_text(strip=True)
            return text if text else None

        return None

    @staticmethod
    def _extract_image_url(tile: Tag) -> str | None:
        """Extract the product image URL from an ``<img>`` tag.

        Args:
            tile: A product-tile Tag.

        Returns:
            The image ``src`` URL, or ``None`` if not found.
        """
        img_tag = tile.find("img")
        if img_tag is None:
            return None
        src = img_tag.get("src") or img_tag.get("data-src")
        if src:
            return str(src).strip()
        return None

    @staticmethod
    def _extract_next_page_url(html: str) -> str | None:
        """Find the next-page pagination link in the HTML.

        Looks for an ``<a>`` tag with class ``next-page`` and returns
        its ``href``.

        Args:
            html: The full page HTML string.

        Returns:
            The absolute or relative URL of the next page, or ``None``
            if there is no next page.
        """
        soup = BeautifulSoup(html, "lxml")
        next_link = soup.find("a", class_="next-page")
        if next_link is None:
            return None
        href = next_link.get("href")
        if not href:
            return None
        href_str = str(href).strip()
        # Make relative URLs absolute
        if href_str.startswith("/"):
            return f"https://www.kaufland.bg{href_str}"
        return href_str
