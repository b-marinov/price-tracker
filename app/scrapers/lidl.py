"""Lidl Bulgaria brochure scraper.

Fetches the current weekly brochure by rendering the JavaScript-based
brochure viewer with Playwright, capturing page screenshots, then
extracting product prices using the Gemma 4 vision LLM parser.

Requires:
    LLM_PARSER_ENABLED=true in settings
    ollama service running with gemma4:e4b pulled
    playwright installed: uv run playwright install chromium --with-deps
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from app.config import get_settings
from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_BROCHURE_URL = "https://www.lidl.bg/broshura"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_PAGES = 20          # safety cap on brochure pages
_PAGE_WAIT_MS = 2000     # wait after navigation for JS to render
_VIEWPORT = {"width": 1280, "height": 900}


class LidlScraper(BaseScraper):
    """Scraper for Lidl Bulgaria.

    Uses Playwright to render the JS-based brochure viewer, captures
    screenshots of each page, and extracts products via Gemma 4 vision.
    Falls back to an empty list if Playwright or the LLM parser is unavailable.
    """

    store_slug: ClassVar[str] = "lidl"

    async def fetch(self) -> list[dict[str, Any]]:
        """Capture screenshots of each Lidl brochure page.

        Returns:
            A list of dicts, each with keys:
            - ``"screenshot"``: raw PNG bytes of one brochure page
            - ``"page_num"``: 1-based page number
        """
        settings = get_settings()
        if not settings.LLM_PARSER_ENABLED:
            logger.info("Lidl scraper: LLM_PARSER_ENABLED=false, skipping")
            return []

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "Lidl scraper: playwright not installed. "
                "Run: uv run playwright install chromium --with-deps"
            )
            return []

        screenshots: list[dict[str, Any]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
            )
            page = await context.new_page()

            try:
                logger.info("Lidl: navigating to %s", _BROCHURE_URL)
                await page.goto(
                    _BROCHURE_URL, wait_until="networkidle", timeout=30_000
                )
                await page.wait_for_timeout(_PAGE_WAIT_MS)

                page_num = 1
                while page_num <= _MAX_PAGES:
                    # Capture current view
                    png_bytes = await page.screenshot(full_page=False)
                    screenshots.append(
                        {"screenshot": png_bytes, "page_num": page_num}
                    )
                    logger.info(
                        "Lidl: captured page %d screenshot", page_num
                    )

                    # Try to advance to next page
                    next_btn = page.locator(
                        "button[aria-label*='next'], "
                        "button[aria-label*='напред'], "
                        ".flipbook-next, "
                        "[data-testid='next-page'], "
                        ".page-next"
                    ).first

                    if not await next_btn.is_visible():
                        logger.info(
                            "Lidl: no next-page button found, "
                            "stopping at page %d",
                            page_num,
                        )
                        break

                    await next_btn.click()
                    await page.wait_for_timeout(_PAGE_WAIT_MS)
                    page_num += 1

            except Exception as exc:  # noqa: BLE001
                logger.warning("Lidl Playwright error: %s", exc)
            finally:
                await browser.close()

        logger.info("Lidl: captured %d page screenshot(s)", len(screenshots))
        return screenshots

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Extract products from brochure screenshots using Gemma 4 vision.

        Args:
            raw: Output of :meth:`fetch` -- list of dicts with ``"screenshot"``
                 (PNG bytes) and ``"page_num"``.

        Returns:
            Flat list of ScrapedItem objects extracted from all screenshots.
        """
        if not raw:
            return []

        settings = get_settings()
        if not settings.LLM_PARSER_ENABLED:
            return []

        try:
            from app.scrapers.llm_parser import (
                OllamaVisionClient,
                extract_from_screenshot,
                llm_items_to_scraped,
            )
        except ImportError:
            logger.warning("Lidl scraper: llm_parser not available")
            return []

        client = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        if not client.is_available():
            logger.warning(
                "Lidl scraper: Ollama not available at %s",
                settings.LLM_OLLAMA_HOST,
            )
            return []

        items: list[ScrapedItem] = []
        for entry in raw:
            png_bytes: bytes = entry["screenshot"]
            page_num: int = entry.get("page_num", 1)
            try:
                llm_items = extract_from_screenshot(
                    png_bytes,
                    store_slug=self.store_slug,
                    client=client,
                )
                scraped = llm_items_to_scraped(llm_items)
                items.extend(scraped)
                logger.info(
                    "Lidl page %d: %d item(s) extracted",
                    page_num,
                    len(scraped),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Lidl parse error on page %d: %s", page_num, exc
                )

        logger.info("Lidl total: %d item(s) extracted", len(items))
        return items
