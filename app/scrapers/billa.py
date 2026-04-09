"""Billa Bulgaria brochure scraper.

Fetches the current weekly brochure PDF via the Billa website → Publitas viewer
chain, then parses it with the PDF brochure parser to extract product prices.

Flow:
    1. GET https://www.billa.bg/promocii/sedmichna-broshura
       → find embedded Publitas viewer URL
    2. GET https://view.publitas.com/billa-bulgaria/... (Publitas page)
       → find direct PDF download link
    3. Parse PDF with pdf_parser
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import httpx

from app.scrapers.base import BaseScraper, ScrapedItem
from app.scrapers.pdf_parser import brochure_items_to_scraped, parse_pdf_brochure

logger = logging.getLogger(__name__)

_BROCHURE_PAGE = "https://www.billa.bg/promocii/sedmichna-broshura"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT_SECONDS = 30

# Matches the Publitas publication base URL embedded in the Billa page
_PUBLITAS_URL_RE = re.compile(
    r"https://view\.publitas\.com/billa-bulgaria/[^\s\"'<>\\]+"
)
# Matches the direct PDF download link inside a Publitas page
_PDF_URL_RE = re.compile(
    r"https://view\.publitas\.com/\d+/\d+/pdfs/[^\"'<>\s]+\.pdf[^\"'<>\s]*"
)


class BillaScraper(BaseScraper):
    """Scraper for Billa Bulgaria.

    Resolves the current weekly brochure PDF URL through the Billa website
    and Publitas viewer, then delegates parsing to the PDF brochure parser.
    """

    store_slug: ClassVar[str] = "billa"

    async def fetch(self) -> list[dict[str, Any]]:
        """Resolve the current Billa weekly brochure PDF URL.

        Steps:
        1. Fetch the Billa weekly brochure page.
        2. Extract the embedded Publitas viewer URL.
        3. Fetch the Publitas page.
        4. Extract the direct PDF download link.

        Returns:
            A list with a single dict containing ``"pdf_url"`` and ``"title"``,
            or an empty list if any step fails.
        """
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            # Step 1: Billa brochure page
            try:
                r1 = await client.get(_BROCHURE_PAGE)
            except httpx.HTTPError as exc:
                logger.warning("HTTP error fetching Billa brochure page: %s", exc)
                return []

            if r1.status_code != 200:
                logger.warning(
                    "Non-200 status %d on Billa brochure page", r1.status_code
                )
                return []

            publitas_matches = _PUBLITAS_URL_RE.findall(r1.text)
            if not publitas_matches:
                logger.warning(
                    "No Publitas viewer URL found on Billa brochure page"
                )
                return []

            # Strip any trailing backslash escapes and get the base viewer URL
            publitas_url = publitas_matches[0].rstrip("\\").split("\\")[0]
            # Ensure it ends without trailing slash
            publitas_base = publitas_url.rstrip("/")
            logger.info("Billa: found Publitas URL %s", publitas_base)

            # Step 2: Publitas viewer page → extract PDF link
            try:
                r2 = await client.get(publitas_base + "/")
            except httpx.HTTPError as exc:
                logger.warning("HTTP error fetching Publitas page: %s", exc)
                return []

            pdf_matches = _PDF_URL_RE.findall(r2.text)
            if not pdf_matches:
                logger.warning("No PDF download URL found on Publitas page")
                return []

            pdf_url = pdf_matches[0]
            logger.info("Billa: found brochure PDF at %s", pdf_url)
            return [{"pdf_url": pdf_url, "title": "Billa weekly brochure"}]

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
                    "Billa PDF parsed: %d items from %s",
                    len(brochure_items),
                    pdf_url,
                )
            except Exception as exc:
                logger.warning("Billa PDF parse error (%s): %s", pdf_url, exc)
        return items
