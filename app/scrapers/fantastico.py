"""Fantastico Bulgaria brochure scraper.

Fetches current weekly brochure PDFs from https://www.fantastico.bg/special-offers/,
resolves any viewer indirection to obtain direct PDF download URLs, then parses
each PDF with the LLM parser (Gemma 4 via Ollama).

Discovery approach:
    1. GET https://www.fantastico.bg/special-offers/
    2. Extract links or embedded viewer URLs for each brochure tile
    3. If a viewer URL is found (FlippingBook etc.), fetch it and extract the PDF URL
    4. Fall back to scanning the page source for .pdf URL patterns

Boris confirmed (2026-04-10): direct PDF download buttons exist within each brochure viewer.
"""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.scrapers.base import BaseScraper, ScrapedItem
from app.scrapers.pdf_parser import brochure_items_to_scraped, parse_pdf_brochure

logger = logging.getLogger(__name__)

_BROCHURES_URL = "https://www.fantastico.bg/special-offers/"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_TIMEOUT_SECONDS = 30
_MAX_PDFS = 5

# Regex to find .pdf URLs anywhere in page source
_PDF_URL_RE = re.compile(r'https?://[^"\'<>\s]+\.pdf[^"\'<>\s]*')

# Known brochure viewer hosts that may wrap a downloadable PDF
_VIEWER_HOSTS = ("flippingbook.com", "publitas.com", "issuu.com")


class FantasticoScraper(BaseScraper):
    """Scraper for Fantastico Bulgaria.

    Fetches the special-offers page, extracts brochure PDF URLs using
    multiple strategies (direct links, data attributes, regex scan, and
    viewer page indirection), then delegates parsing to the PDF parser.
    """

    store_slug: ClassVar[str] = "fantastico"

    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch the Fantastico special-offers page and extract PDF URLs.

        Tries multiple extraction strategies in order:
            a. Direct ``<a href="*.pdf">`` links on the page.
            b. ``data-*`` attributes containing PDF URLs.
            c. Regex scan of full page source for ``.pdf`` URLs.
            d. Follow links to known viewer hosts (FlippingBook, Publitas,
               Issuu) and repeat strategies a-c on each viewer page.

        Returns:
            A list of dicts with keys ``"pdf_url"`` and ``"title"``,
            capped at :data:`_MAX_PDFS`. Returns an empty list on failure.
        """
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        ) as client:
            # Step 1: fetch the main special-offers page
            try:
                response = await client.get(_BROCHURES_URL)
            except httpx.HTTPError as exc:
                logger.warning(
                    "HTTP error fetching Fantastico special-offers page: %s", exc
                )
                return []

            if response.status_code != 200:
                logger.warning(
                    "Non-200 status %d fetching Fantastico special-offers page",
                    response.status_code,
                )
                return []

            page_source = response.text
            soup = BeautifulSoup(page_source, "lxml")

            # Collect PDF URLs from the main page
            pdf_urls: list[str] = []
            pdf_urls.extend(self._extract_direct_pdf_links(soup))
            pdf_urls.extend(self._extract_data_attr_pdfs(soup))
            pdf_urls.extend(self._extract_pdf_urls_by_regex(page_source))

            # Step 2: look for viewer host links and resolve them
            viewer_urls = self._extract_viewer_urls(soup, page_source)
            for viewer_url in viewer_urls:
                try:
                    viewer_resp = await client.get(viewer_url)
                except httpx.HTTPError as exc:
                    logger.debug(
                        "Could not fetch viewer URL %s: %s", viewer_url, exc
                    )
                    continue

                if viewer_resp.status_code != 200:
                    continue

                viewer_source = viewer_resp.text
                viewer_soup = BeautifulSoup(viewer_source, "lxml")
                pdf_urls.extend(self._extract_direct_pdf_links(viewer_soup))
                pdf_urls.extend(self._extract_data_attr_pdfs(viewer_soup))
                pdf_urls.extend(self._extract_pdf_urls_by_regex(viewer_source))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_urls: list[str] = []
        for url in pdf_urls:
            normalised = url.split("?")[0]  # dedupe ignoring query params
            if normalised not in seen:
                seen.add(normalised)
                unique_urls.append(url)

        if not unique_urls:
            logger.warning(
                "FantasticoScraper: 0 PDF URLs found on special-offers page"
            )
            return []

        # Cap results
        unique_urls = unique_urls[:_MAX_PDFS]

        results: list[dict[str, Any]] = []
        for idx, url in enumerate(unique_urls, start=1):
            logger.info("Fantastico: found brochure PDF #%d at %s", idx, url)
            results.append(
                {"pdf_url": url, "title": f"Fantastico brochure {idx}"}
            )

        return results

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Parse PDF brochures into ScrapedItem instances.

        Uses the LLM parser (Gemma 4 via Ollama) when ``LLM_PARSER_ENABLED=true``
        in settings, otherwise falls back to the regex-based PDF parser.

        Args:
            raw: Output of :meth:`fetch` -- list of dicts with ``"pdf_url"``.

        Returns:
            Flat list of ScrapedItem objects extracted from all PDFs.
        """
        settings = get_settings()
        items: list[ScrapedItem] = []
        for entry in raw:
            pdf_url = entry.get("pdf_url", "")
            if not pdf_url:
                continue
            try:
                if settings.LLM_PARSER_ENABLED:
                    from app.scrapers.llm_parser import (
                        OllamaVisionClient,
                        llm_items_to_scraped,
                        parse_pdf_with_llm,
                    )

                    client = OllamaVisionClient(
                        host=settings.LLM_OLLAMA_HOST,
                        model=settings.LLM_MODEL,
                        temperature=settings.LLM_TEMPERATURE,
                        timeout=settings.LLM_TIMEOUT_SECONDS,
                    )
                    llm_items = parse_pdf_with_llm(
                        pdf_url,
                        store_slug=self.store_slug,
                        dpi=settings.LLM_PAGE_DPI,
                        client=client,
                    )
                    scraped = llm_items_to_scraped(llm_items)
                    items.extend(scraped)
                    logger.info(
                        "Fantastico PDF parsed via LLM: %d items from %s",
                        len(scraped),
                        pdf_url,
                    )
                else:
                    brochure_items = parse_pdf_brochure(
                        pdf_url, store_slug=self.store_slug
                    )
                    items.extend(brochure_items_to_scraped(brochure_items))
                    logger.info(
                        "Fantastico PDF parsed: %d items from %s",
                        len(brochure_items),
                        pdf_url,
                    )
            except Exception as exc:
                logger.warning(
                    "Fantastico PDF parse error (%s): %s",
                    pdf_url,
                    exc,
                    exc_info=True,
                )
        return items

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_direct_pdf_links(soup: BeautifulSoup) -> list[str]:
        """Find ``<a>`` tags whose ``href`` ends with ``.pdf`` (case-insensitive).

        Args:
            soup: Parsed HTML tree.

        Returns:
            List of absolute PDF URLs found.
        """
        urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
                if href.startswith("http"):
                    urls.append(href)
        return urls

    @staticmethod
    def _extract_data_attr_pdfs(soup: BeautifulSoup) -> list[str]:
        """Scan all elements for ``data-*`` attributes containing PDF URLs.

        Args:
            soup: Parsed HTML tree.

        Returns:
            List of absolute PDF URLs found in data attributes.
        """
        urls: list[str] = []
        for tag in soup.find_all(True):
            for attr_name, attr_value in tag.attrs.items():
                if not attr_name.startswith("data-"):
                    continue
                if isinstance(attr_value, str) and ".pdf" in attr_value.lower():
                    matches = _PDF_URL_RE.findall(attr_value)
                    urls.extend(matches)
        return urls

    @staticmethod
    def _extract_pdf_urls_by_regex(source: str) -> list[str]:
        """Regex scan the full page source for ``.pdf`` URLs.

        Args:
            source: Raw HTML source text.

        Returns:
            List of PDF URLs found via regex.
        """
        return _PDF_URL_RE.findall(source)

    @staticmethod
    def _extract_viewer_urls(
        soup: BeautifulSoup, source: str
    ) -> list[str]:
        """Find links to known brochure viewer hosts.

        Checks both ``<a href>`` and ``<iframe src>`` attributes, plus a
        regex scan for viewer host URLs in the page source.

        Args:
            soup: Parsed HTML tree.
            source: Raw HTML source text.

        Returns:
            Deduplicated list of viewer URLs to follow.
        """
        urls: list[str] = []

        # Check <a href> and <iframe src>
        for tag in soup.find_all(["a", "iframe"]):
            url = tag.get("href") or tag.get("src") or ""
            if any(host in url for host in _VIEWER_HOSTS):
                urls.append(url)

        # Regex scan for viewer host URLs
        for host in _VIEWER_HOSTS:
            pattern = re.compile(
                rf'https?://[^"\'<>\s]*{re.escape(host)}[^"\'<>\s]*'
            )
            urls.extend(pattern.findall(source))

        # Deduplicate
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            clean = url.rstrip("/")
            if clean not in seen:
                seen.add(clean)
                unique.append(url)

        return unique
