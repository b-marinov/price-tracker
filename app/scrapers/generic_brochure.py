"""Generic LLM-powered brochure scraper — works for any grocery store.

A single scraper class replaces all store-specific scrapers.

Phase 1 — Playwright renders the brochure listing page, then Gemma 4
           discovers the direct PDF download URL(s).
Phase 2 — The existing PDF→LLM pipeline extracts product offers from the PDF.

Store config lives entirely in the ``stores`` table (``brochure_url`` column).
Adding a new store requires only a DB row — no Python code.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_NAV_TIMEOUT = 60_000       # Playwright page navigation timeout (ms)
_PAGE_WAIT_MS = 4_000       # extra wait after load for JS rendering (ms)
_MAX_LINKS = 300            # max links to send to LLM for text-mode discovery
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}
# Viewer wrapper hosts — skip when building the link list for LLM
_VIEWER_HOSTS = (
    "publitas.com",
    "flippingbook.com",
    "issuu.com",
    "view.publitas",
)


class GenericBrochureScraper(BaseScraper):
    """LLM-powered brochure scraper that works for any grocery store.

    Instantiate with the store's slug and brochure listing URL; no subclassing
    required.  Gemma 4 handles both PDF URL discovery and content extraction.

    Attributes:
        store_slug: Unique store slug (shadows the ClassVar per instance).
        brochure_listing_url: URL of the page that lists current brochures.
    """

    store_slug: ClassVar[str] = "generic"  # overridden per instance in __init__

    def __init__(self, store_slug: str, brochure_listing_url: str) -> None:
        self.store_slug = store_slug  # type: ignore[misc]  # shadows ClassVar
        self.brochure_listing_url = brochure_listing_url

    # ------------------------------------------------------------------
    # Phase 1 — PDF URL discovery
    # ------------------------------------------------------------------

    async def fetch(self) -> list[dict[str, Any]]:
        """Discover current brochure PDF URL(s) via Playwright + Gemma 4.

        Discovery strategy (tried in order):
        1. Playwright renders the listing page (handles JS-rendered sites).
        2. JS query collects all ``<a href="*.pdf">`` direct links.
           - One link  → use it directly.
           - Many links → LLM (text mode) picks the current brochure.
        3. No direct PDFs → collect all page links → LLM text analysis.
        4. LLM text fails → full-page JPEG screenshot → LLM vision mode.

        Returns:
            List of ``{"pdf_url": str, "title": str}`` dicts, or ``[]``
            if no PDF could be discovered.
        """
        from app.config import get_settings

        settings = get_settings()

        if not settings.LLM_PARSER_ENABLED:
            logger.info(
                "%s: LLM_PARSER_ENABLED=false — skipping fetch", self.store_slug
            )
            return []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "%s: playwright not installed. "
                "Run: uv run playwright install chromium --with-deps",
                self.store_slug,
            )
            return []

        from app.scrapers.llm_parser import (
            OllamaVisionClient,
            discover_pdf_urls,
            discover_pdf_urls_from_screenshot,
        )

        llm = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        if not llm.is_available():
            logger.warning(
                "%s: Ollama not available — skipping fetch", self.store_slug
            )
            return []

        pdf_entries: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
            )
            page = await context.new_page()

            try:
                logger.info(
                    "%s: navigating to %s", self.store_slug, self.brochure_listing_url
                )
                await page.goto(
                    self.brochure_listing_url,
                    wait_until="load",
                    timeout=_NAV_TIMEOUT,
                )
                await page.wait_for_timeout(_PAGE_WAIT_MS)

                page_title = await page.title() or self.store_slug

                # Strategy 1 — direct PDF links already in the DOM
                direct_links: list[dict[str, str]] = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]'))"
                    ".map(a => ({href: a.href, text: (a.textContent || '').trim()}))"
                    ".filter(a => a.href.toLowerCase().includes('.pdf'))"
                )

                if direct_links:
                    logger.info(
                        "%s: %d direct PDF link(s) found in DOM",
                        self.store_slug, len(direct_links),
                    )
                    if len(direct_links) == 1:
                        pdf_url = direct_links[0]["href"]
                    else:
                        link_text = "\n".join(
                            f"- {lnk['text'][:80]} → {lnk['href']}"
                            for lnk in direct_links
                        )
                        prompt = (
                            f"Store: {self.store_slug}\n"
                            f"Page title: {page_title}\n"
                            f"Direct PDF links on page:\n{link_text}"
                        )
                        chosen = discover_pdf_urls(prompt, client=llm)
                        pdf_url = chosen[0] if chosen else direct_links[0]["href"]

                    logger.info("%s: PDF URL → %s", self.store_slug, pdf_url)
                    pdf_entries.append({"pdf_url": pdf_url, "title": page_title})
                    return pdf_entries

                # Strategy 2 — LLM text analysis of all page links
                logger.info(
                    "%s: no direct PDF links; trying LLM text analysis",
                    self.store_slug,
                )
                all_links: list[dict[str, str]] = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]'))"
                    f".map(a => ({{href: a.href, text: (a.textContent || '').trim()}}))"
                    f".filter(a => a.href.startsWith('http'))"
                    f".slice(0, {_MAX_LINKS})"
                )
                filtered_links = [
                    lnk for lnk in all_links
                    if not any(h in lnk["href"] for h in _VIEWER_HOSTS)
                ]
                link_text = "\n".join(
                    f"- {lnk['text'][:80]} → {lnk['href']}"
                    for lnk in filtered_links
                )
                prompt = (
                    f"Store: {self.store_slug}\n"
                    f"Page title: {page_title}\n"
                    f"All links on brochure listing page:\n{link_text}"
                )
                urls = discover_pdf_urls(prompt, client=llm)

                if urls:
                    logger.info(
                        "%s: LLM text discovery → %s", self.store_slug, urls[0]
                    )
                    pdf_entries.append({"pdf_url": urls[0], "title": page_title})
                    return pdf_entries

                # Strategy 3 — screenshot → LLM vision fallback
                logger.info(
                    "%s: LLM text failed; trying screenshot/vision fallback",
                    self.store_slug,
                )
                screenshot_bytes: bytes = await page.screenshot(
                    type="jpeg",
                    quality=75,
                    full_page=False,
                )
                image_b64 = base64.b64encode(screenshot_bytes).decode()
                urls = discover_pdf_urls_from_screenshot(image_b64, client=llm)

                if urls:
                    logger.info(
                        "%s: vision discovery → %s", self.store_slug, urls[0]
                    )
                    pdf_entries.append({"pdf_url": urls[0], "title": page_title})
                else:
                    logger.warning(
                        "%s: all discovery strategies exhausted — no PDF found",
                        self.store_slug,
                    )

            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: Playwright error: %s", self.store_slug, exc)
            finally:
                await browser.close()

        return pdf_entries

    # ------------------------------------------------------------------
    # Phase 2 — PDF content extraction
    # ------------------------------------------------------------------

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Parse brochure PDFs into ScrapedItem instances via Gemma 4.

        Uses LLM parsing when ``LLM_PARSER_ENABLED=true``, otherwise falls
        back to the regex-based PDF parser.

        Args:
            raw: Output of :meth:`fetch` — list of dicts with ``"pdf_url"``.

        Returns:
            Flat list of :class:`~app.scrapers.base.ScrapedItem` objects.
        """
        from app.config import get_settings
        from app.scrapers.llm_parser import (
            OllamaVisionClient,
            llm_items_to_scraped,
            parse_pdf_with_llm,
        )
        from app.scrapers.pdf_parser import brochure_items_to_scraped, parse_pdf_brochure

        settings = get_settings()
        llm = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        items: list[ScrapedItem] = []
        for entry in raw:
            pdf_url = entry.get("pdf_url", "")
            if not pdf_url:
                continue
            try:
                if settings.LLM_PARSER_ENABLED:
                    llm_items = parse_pdf_with_llm(
                        pdf_url,
                        store_slug=self.store_slug,
                        dpi=settings.LLM_PAGE_DPI,
                        client=llm,
                    )
                    scraped = llm_items_to_scraped(llm_items)
                    items.extend(scraped)
                    logger.info(
                        "%s: PDF parsed via LLM — %d items from %s",
                        self.store_slug, len(scraped), pdf_url,
                    )
                else:
                    brochure_items = parse_pdf_brochure(
                        pdf_url, store_slug=self.store_slug
                    )
                    items.extend(brochure_items_to_scraped(brochure_items))
                    logger.info(
                        "%s: PDF parsed — %d items from %s",
                        self.store_slug, len(brochure_items), pdf_url,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%s: PDF parse error (%s): %s",
                    self.store_slug, pdf_url, exc, exc_info=True,
                )
        return items
