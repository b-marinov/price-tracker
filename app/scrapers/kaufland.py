"""Kaufland Bulgaria brochure scraper.

Fetches the current weekly brochure PDF from https://www.kaufland.bg/broshuri.html,
then parses it with the PDF brochure parser to extract product prices.
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper, ScrapedItem
from app.scrapers.pdf_parser import brochure_items_to_scraped, parse_pdf_brochure

logger = logging.getLogger(__name__)

_BROCHURES_URL = "https://www.kaufland.bg/broshuri.html"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT_SECONDS = 30


class KauflandScraper(BaseScraper):
    """Scraper for Kaufland Bulgaria.

    Fetches the brochures listing page, extracts PDF download URLs from
    ``m-flyer-tile`` elements, then uses the PDF parser to extract products.
    Prefers the main food brochure (``parameter="aktualna-broshura"``).
    Falls back to the first available tile if the preferred one is not found.
    """

    store_slug: ClassVar[str] = "kaufland"

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch the Kaufland brochures page and extract PDF download URLs.

        Returns:
            A list of dicts with keys ``"pdf_url"`` and ``"title"``.
        """
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            try:
                response = await client.get(_BROCHURES_URL)
            except httpx.HTTPError as exc:
                logger.warning("HTTP error fetching Kaufland brochures page: %s", exc)
                return []

            if response.status_code != 200:
                logger.warning(
                    "Non-200 status %d fetching Kaufland brochures page",
                    response.status_code,
                )
                return []

        soup = BeautifulSoup(response.text, "lxml")
        tiles = soup.find_all("div", class_="m-flyer-tile")

        if not tiles:
            logger.warning("No m-flyer-tile elements found on Kaufland brochures page")
            return []

        # Prefer the main food brochure tile
        chosen = next(
            (t for t in tiles if t.get("data-parameter") == "aktualna-broshura"),
            tiles[0],
        )
        pdf_url = chosen.get("data-download-url", "")
        title = chosen.get("data-aa-detail", "Kaufland brochure")

        if not pdf_url:
            logger.warning("No data-download-url on Kaufland flyer tile")
            return []

        logger.info("Kaufland: found brochure PDF at %s", pdf_url)
        return [{"pdf_url": pdf_url, "title": title}]

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Parse PDF brochures into ScrapedItem instances.

        Args:
            raw: Output of :meth:`fetch` — list of dicts with ``"pdf_url"``.

        Returns:
            Flat list of ScrapedItem objects extracted from all PDFs.
        """
        items: list[ScrapedItem] = []
        for entry in raw:
            pdf_url = entry.get("pdf_url", "")
            if not pdf_url:
                continue
            try:
                brochure_items = parse_pdf_brochure(pdf_url, store_slug=self.store_slug)
                items.extend(brochure_items_to_scraped(brochure_items))
                logger.info(
                    "Kaufland PDF parsed: %d items from %s",
                    len(brochure_items),
                    pdf_url,
                )
            except Exception as exc:
                logger.warning("Kaufland PDF parse error (%s): %s", pdf_url, exc)
        return items
