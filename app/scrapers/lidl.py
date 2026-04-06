"""Lidl Bulgaria weekly offers web scraper.

Scrapes weekly offer listings from https://www.lidl.bg/c/sedmichni-predlozheniya
with pagination support (up to 10 pages).

Dependencies (already approved):
- beautifulsoup4 (HTML parsing)
- lxml (fast HTML parser backend)
- httpx (async HTTP client)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.lidl.bg/c/sedmichni-predlozheniya"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_PAGES = 10
_TIMEOUT_SECONDS = 30


class LidlScraper(BaseScraper):
    """Scraper for Lidl Bulgaria weekly offers.

    Fetches the weekly offers page from the Lidl Bulgaria website,
    parses offer cards for name, price, unit, image, and validity dates,
    and normalises them into ``ScrapedItem`` instances.
    """

    store_slug: ClassVar[str] = "lidl"

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch weekly offer pages from Lidl Bulgaria.

        Makes async HTTP GET requests starting from the base weekly offers
        URL, following pagination links up to a maximum of ``_MAX_PAGES``
        pages. Stops early if a non-200 response is received or no
        next-page link is found.

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

            offer_cards = soup.find_all("article", class_="offer-card")
            for card in offer_cards:
                item = self._parse_card(card, page_num)
                if item is not None:
                    items.append(item)

        return items

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_card(self, card: Tag, page_num: int) -> ScrapedItem | None:
        """Extract a single product from an offer-card element.

        Args:
            card: An ``<article class="offer-card">`` BeautifulSoup Tag.
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
        validity_from = self._extract_validity_date(card, "validity-from")
        validity_to = self._extract_validity_date(card, "validity-to")

        raw_data: dict = {
            "page": page_num,
            "raw_html": str(card)[:500],
        }
        if validity_from:
            raw_data["validity_from"] = validity_from
        if validity_to:
            raw_data["validity_to"] = validity_to

        return ScrapedItem(
            name=name,
            price=price,
            currency="EUR",
            unit=unit,
            image_url=image_url,
            source="web",
            raw=raw_data,
        )

    @staticmethod
    def _extract_name(card: Tag) -> str | None:
        """Extract product name from the offer card.

        Args:
            card: An offer-card Tag.

        Returns:
            The product name string, or ``None`` if not found.
        """
        title_tag = card.find("p", class_="offer-card__title")
        if title_tag is None:
            return None
        text = title_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_price(card: Tag) -> Decimal | None:
        """Extract and parse the product price from the offer card.

        Looks inside a ``<div class="pricebox">`` for a price element.
        Strips the Bulgarian Lev suffix (``лв.`` / ``лв``), removes
        whitespace and commas, then converts to ``Decimal``.

        Args:
            card: An offer-card Tag.

        Returns:
            The price as a ``Decimal``, or ``None`` if parsing fails.
        """
        pricebox = card.find("div", class_="pricebox")
        if pricebox is None:
            return None

        price_tag = pricebox.find("span", class_="pricebox__price")
        if price_tag is None:
            return None

        raw_price = price_tag.get_text(strip=True)
        # Remove currency suffix, whitespace, and normalise decimal separator
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
            card: An offer-card Tag.

        Returns:
            The unit string, or ``None`` if not found.
        """
        unit_tag = card.find("span", class_="pricebox__unit")
        if unit_tag is None:
            return None
        text = unit_tag.get_text(strip=True)
        return text if text else None

    @staticmethod
    def _extract_image_url(card: Tag) -> str | None:
        """Extract the product image URL from an ``<img>`` tag.

        Args:
            card: An offer-card Tag.

        Returns:
            The image ``src`` URL, or ``None`` if not found.
        """
        img_tag = card.find("img")
        if img_tag is None:
            return None
        src = img_tag.get("src") or img_tag.get("data-src")
        if src:
            return str(src).strip()
        return None

    @staticmethod
    def _extract_validity_date(card: Tag, css_class: str) -> str | None:
        """Extract a validity date string from the card.

        Looks for a ``<span>`` with the given CSS class and attempts
        to parse a date in ``DD.MM.YYYY`` format.

        Args:
            card: An offer-card Tag.
            css_class: The CSS class of the date element
                (e.g. ``"validity-from"``, ``"validity-to"``).

        Returns:
            The date as an ISO format string (``YYYY-MM-DD``), or ``None``
            if not found or unparseable.
        """
        date_tag = card.find("span", class_=css_class)
        if date_tag is None:
            return None

        raw_text = date_tag.get_text(strip=True)
        if not raw_text:
            return None

        # Try DD.MM.YYYY format (common Bulgarian date format)
        match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw_text)
        if match:
            day, month, year = match.groups()
            try:
                dt = datetime(int(year), int(month), int(day))
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                logger.debug("Invalid date values: %s", raw_text)
                return None

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
            return f"https://www.lidl.bg{href_str}"
        return href_str
