"""Fantastico Bulgaria web scraper.

Scrapes promotional product listings from https://fantastico.bg/promotions
with pagination support (up to 10 pages).

Dependencies: beautifulsoup4, lxml, httpx (all approved).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_BASE_URL = "https://fantastico.bg/promotions"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_PAGES = 10
_TIMEOUT_SECONDS = 30


class FantasticoScraper(BaseScraper):
    """Scraper for Fantastico Bulgaria promotional listings.

    Fetches promotion pages from the Fantastico Bulgaria website,
    parses product cards and promotion items for name, price, unit,
    and image, and normalises them into ``ScrapedItem`` instances.
    """

    store_slug: ClassVar[str] = "fantastico"

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch promotional listing pages from Fantastico Bulgaria.

        Makes async HTTP GET requests starting from the base promotions URL,
        following pagination links up to a maximum of ``_MAX_PAGES`` pages.
        Stops early if a non-200 response is received or no next-page link
        is found.

        Returns:
            A list of dicts, each with keys ``"html"`` (page source) and
            ``"page"`` (1-based page number).
        """
        pages: list[dict[str, Any]] = []
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

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Parse raw page HTML into a list of ``ScrapedItem`` objects.

        Each entry in *raw* is expected to be a dict with keys ``"html"``
        (the full page HTML string) and ``"page"`` (the 1-based page number).

        Looks for products inside ``<div class="product-card">`` and
        ``<div class="promotion-item">`` containers.

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

            # Match both product-card and promotion-item containers
            product_cards = soup.find_all(
                "div", class_=lambda c: c and c in ("product-card", "promotion-item")
            )
            for card in product_cards:
                item = self._parse_card(card, page_num)
                if item is not None:
                    items.append(item)

        return items

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_card(self, card: Tag, page_num: int) -> ScrapedItem | None:
        """Extract a single product from a product-card or promotion-item element.

        Args:
            card: A ``<div class="product-card">`` or
                ``<div class="promotion-item">`` BeautifulSoup Tag.
            page_num: The page this card came from (for raw metadata).

        Returns:
            A ``ScrapedItem`` or ``None`` if required fields are missing.
        """
        name = self._extract_name(card)
        if not name:
            logger.debug("Skipping card on page %d — no product name found", page_num)
            return None

        price = self._extract_price(card)
        if price is None:
            logger.debug(
                "Skipping card '%s' on page %d — no valid price", name, page_num
            )
            return None

        unit = self._extract_unit(card)
        image_url = self._extract_image_url(card)

        return ScrapedItem(
            name=name,
            price=price,
            currency="EUR",
            unit=unit,
            image_url=image_url,
            source="web",
            raw={
                "page": page_num,
                "raw_html": str(card)[:500],
            },
        )

    @staticmethod
    def _extract_name(card: Tag) -> str | None:
        """Extract product name from the card.

        Args:
            card: A product card Tag.

        Returns:
            The product name string, or ``None`` if not found.
        """
        name_tag = card.find("h3", class_="product-name")
        if name_tag is None:
            return None
        text = name_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_price(card: Tag) -> Decimal | None:
        """Extract and parse the product price from the card.

        Strips the Bulgarian Lev suffix (``лв.`` / ``лв``), removes
        whitespace and commas, then converts to ``Decimal``.

        Args:
            card: A product card Tag.

        Returns:
            The price as a ``Decimal``, or ``None`` if parsing fails.
        """
        price_tag = card.find("span", class_="product-price")
        if price_tag is None:
            return None

        raw_price = price_tag.get_text(strip=True)
        cleaned = (
            raw_price.replace("€", "").replace("eur", "").replace("евро", "").replace("лв.", "")
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
    def _extract_unit(card: Tag) -> str | None:
        """Extract the unit descriptor (e.g. kg, l, бр) from the card.

        Args:
            card: A product card Tag.

        Returns:
            The unit string, or ``None`` if not found.
        """
        unit_tag = card.find("span", class_="product-unit")
        if unit_tag is None:
            return None
        text = unit_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_image_url(card: Tag) -> str | None:
        """Extract the product image URL from an ``<img>`` tag.

        Checks both ``src`` and ``data-src`` attributes for lazy-loaded images.

        Args:
            card: A product card Tag.

        Returns:
            The image URL string, or ``None`` if not found.
        """
        img_tag = card.find("img")
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
            return f"https://fantastico.bg{href_str}"
        return href_str
