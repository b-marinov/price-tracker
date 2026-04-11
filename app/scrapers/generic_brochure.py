"""Generic LLM-powered brochure scraper — works for any grocery store.

A single scraper class replaces all store-specific scrapers.

Phase 1 — Playwright renders the brochure listing page, discovers the
           brochure URL (direct PDF or interactive viewer), then captures
           content either by downloading the PDF or by screenshotting each
           viewer page.

Phase 2 — Gemma 4 vision extracts product offers from each image.

Store config lives entirely in the ``stores`` table (``brochure_url`` column).
Adding a new store requires only a DB row — no Python code.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_NAV_TIMEOUT = 60_000        # Playwright page navigation timeout (ms)
_PAGE_WAIT_MS = 4_000        # extra wait after load for JS rendering (ms)
_TURN_WAIT_MS = 2_000        # wait after advancing a viewer page (ms)
_MAX_LINKS = 300             # max links to send to LLM for text-mode discovery
_MAX_VIEWER_PAGES = 60       # maximum brochure pages to screenshot
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}

# CSS selectors tried (in order) to advance to the next brochure page
_NEXT_PAGE_SELECTORS = [
    "[aria-label='Next page']",
    "[aria-label='next page']",
    "[aria-label='Следваща страница']",
    ".next-page",
    ".btn-next",
    ".arrow-next",
    "[data-direction='next']",
    "[class*='next']",
    "[class*='arrow-right']",
    "[class*='forward']",
]


class GenericBrochureScraper(BaseScraper):
    """LLM-powered brochure scraper that works for any grocery store.

    Instantiate with the store's slug and brochure listing URL; no subclassing
    required.  Gemma 4 handles PDF URL discovery and content extraction.

    Attributes:
        store_slug: Unique store slug (shadows the ClassVar per instance).
        brochure_listing_url: URL of the page that lists current brochures.
    """

    store_slug: ClassVar[str] = "generic"  # overridden per instance in __init__

    def __init__(self, store_slug: str, brochure_listing_url: str) -> None:
        self.store_slug = store_slug  # type: ignore[misc]
        self.brochure_listing_url = brochure_listing_url

    # ------------------------------------------------------------------
    # Phase 1 — brochure discovery + capture
    # ------------------------------------------------------------------

    async def fetch(self) -> list[dict[str, Any]]:
        """Discover the current brochure and capture its content.

        Discovery strategy (tried in order):
        1. Playwright renders the listing page.
        2. Direct ``.pdf`` links in DOM → use immediately.
        3. LLM text analysis of all page links → picks brochure URL.
        4. Screenshot fallback → LLM vision identifies the viewer URL.

        After a URL is found:
        - If it ends in ``.pdf`` → return as ``{"pdf_url": ...}``
          (legacy PDF path kept for stores that serve real PDFs).
        - Otherwise → navigate into the viewer with Playwright,
          screenshot every page, return ``{"screenshots": [...], "title": ...}``.

        Returns:
            List of one entry per brochure:
            ``{"pdf_url": str, "title": str}`` **or**
            ``{"screenshots": list[str], "title": str}`` (base64 JPEGs).
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
                "%s: playwright not installed — run: "
                "uv run playwright install chromium --with-deps",
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

                # Strategy 1 — direct .pdf links in the DOM
                direct_links: list[dict[str, str]] = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]'))"
                    ".map(a => ({href: a.href, text: (a.textContent || '').trim()}))"
                    ".filter(a => a.href.toLowerCase().includes('.pdf'))"
                )

                brochure_url: str | None = None

                if direct_links:
                    logger.info(
                        "%s: %d direct PDF link(s) in DOM",
                        self.store_slug, len(direct_links),
                    )
                    if len(direct_links) == 1:
                        brochure_url = direct_links[0]["href"]
                    else:
                        link_text = "\n".join(
                            f"- {lnk['text'][:80]} → {lnk['href']}"
                            for lnk in direct_links
                        )
                        prompt = (
                            f"Store: {self.store_slug}\n"
                            f"Page title: {page_title}\n"
                            f"Direct PDF links:\n{link_text}"
                        )
                        chosen = discover_pdf_urls(prompt, client=llm)
                        brochure_url = chosen[0] if chosen else direct_links[0]["href"]

                else:
                    # Strategy 2 — LLM text analysis
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
                    link_text = "\n".join(
                        f"- {lnk['text'][:80]} → {lnk['href']}"
                        for lnk in all_links
                    )
                    prompt = (
                        f"Store: {self.store_slug}\n"
                        f"Page title: {page_title}\n"
                        f"All links on brochure listing page:\n{link_text}"
                    )
                    urls = discover_pdf_urls(prompt, client=llm)

                    if urls:
                        brochure_url = urls[0]
                        logger.info(
                            "%s: LLM text → %s", self.store_slug, brochure_url
                        )
                    else:
                        # Strategy 3 — screenshot vision fallback
                        logger.info(
                            "%s: LLM text failed; trying vision fallback",
                            self.store_slug,
                        )
                        shot = await page.screenshot(
                            type="jpeg", quality=75, full_page=False
                        )
                        image_b64 = base64.b64encode(shot).decode()
                        urls = discover_pdf_urls_from_screenshot(image_b64, client=llm)
                        if urls:
                            brochure_url = urls[0]
                            logger.info(
                                "%s: vision → %s", self.store_slug, brochure_url
                            )
                        else:
                            logger.warning(
                                "%s: all strategies exhausted — no brochure found",
                                self.store_slug,
                            )

                if not brochure_url:
                    return []

                # Direct PDF → return url for legacy download path
                if brochure_url.lower().endswith(".pdf"):
                    logger.info(
                        "%s: direct PDF → %s", self.store_slug, brochure_url
                    )
                    return [{"pdf_url": brochure_url, "title": page_title}]

                # Interactive viewer → screenshot every page
                logger.info(
                    "%s: viewer detected → screenshotting pages at %s",
                    self.store_slug, brochure_url,
                )
                screenshots = await self._screenshot_viewer_pages(
                    page, brochure_url
                )
                if screenshots:
                    return [{"screenshots": screenshots, "title": page_title}]

                logger.warning(
                    "%s: viewer screenshotting yielded 0 pages", self.store_slug
                )
                return []

            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: fetch error: %s", self.store_slug, exc)
                return []
            finally:
                await browser.close()

    async def _screenshot_viewer_pages(
        self,
        page: Any,
        viewer_url: str,
    ) -> list[str]:
        """Navigate a brochure viewer and return base64 JPEG screenshots per page.

        Advances through the viewer by trying common "next page" selectors then
        falling back to the keyboard → arrow key. Stops when the page content
        stops changing or ``_MAX_VIEWER_PAGES`` is reached.

        Args:
            page: Active Playwright ``Page`` object.
            viewer_url: URL of the interactive brochure viewer.

        Returns:
            List of base64-encoded JPEG strings, one per brochure page.
        """
        await page.goto(viewer_url, wait_until="load", timeout=_NAV_TIMEOUT)
        await page.wait_for_timeout(_PAGE_WAIT_MS)

        screenshots: list[str] = []
        prev_hash = ""

        for page_num in range(_MAX_VIEWER_PAGES):
            shot_bytes: bytes = await page.screenshot(
                type="jpeg", quality=80, full_page=False
            )
            current_hash = hashlib.md5(shot_bytes).hexdigest()  # noqa: S324

            if current_hash == prev_hash:
                logger.info(
                    "%s: viewer page %d unchanged — end of brochure",
                    self.store_slug, page_num,
                )
                break

            prev_hash = current_hash
            screenshots.append(base64.b64encode(shot_bytes).decode())
            logger.debug(
                "%s: screenshotted viewer page %d", self.store_slug, page_num + 1
            )

            # Try to advance to the next page
            advanced = False
            for selector in _NEXT_PAGE_SELECTORS:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        await page.wait_for_timeout(_TURN_WAIT_MS)
                        advanced = True
                        break
                except Exception:  # noqa: BLE001
                    continue

            if not advanced:
                # Fallback: keyboard right arrow (works in most flipbook viewers)
                await page.keyboard.press("ArrowRight")
                await page.wait_for_timeout(_TURN_WAIT_MS)

        logger.info(
            "%s: captured %d viewer page(s)", self.store_slug, len(screenshots)
        )
        return screenshots

    # ------------------------------------------------------------------
    # Phase 2 — content extraction
    # ------------------------------------------------------------------

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Extract product offers from brochure images via Gemma 4.

        Handles two input formats from :meth:`fetch`:
        - ``{"pdf_url": str}``  — download PDF, render pages, vision extract.
        - ``{"screenshots": list[str]}`` — use Playwright screenshots directly.

        Args:
            raw: Output of :meth:`fetch`.

        Returns:
            Flat list of :class:`~app.scrapers.base.ScrapedItem` objects.
        """
        from app.config import get_settings
        from app.scrapers.llm_parser import (
            LLMBrochureItem,
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
            try:
                screenshots: list[str] | None = entry.get("screenshots")
                pdf_url: str = entry.get("pdf_url", "")

                if screenshots:
                    # Vision extraction from Playwright screenshots
                    if not settings.LLM_PARSER_ENABLED:
                        logger.info(
                            "%s: LLM disabled — skipping %d screenshot page(s)",
                            self.store_slug, len(screenshots),
                        )
                        continue

                    all_llm_items: list[LLMBrochureItem] = []
                    for idx, b64 in enumerate(screenshots):
                        try:
                            page_items = llm.extract_from_image(b64, page_num=idx + 1)
                            all_llm_items.extend(page_items)
                            logger.debug(
                                "%s: page %d → %d raw items",
                                self.store_slug, idx + 1, len(page_items),
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "%s: vision error on page %d: %s",
                                self.store_slug, idx + 1, exc,
                            )

                    scraped = llm_items_to_scraped(all_llm_items)
                    items.extend(scraped)
                    logger.info(
                        "%s: %d page(s) → %d items (viewer screenshots)",
                        self.store_slug, len(screenshots), len(scraped),
                    )

                elif pdf_url:
                    # Legacy: direct PDF download + LLM or regex parser
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
                            "%s: %d items from PDF %s",
                            self.store_slug, len(scraped), pdf_url,
                        )
                    else:
                        brochure_items = parse_pdf_brochure(
                            pdf_url, store_slug=self.store_slug
                        )
                        items.extend(brochure_items_to_scraped(brochure_items))

            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: parse error: %s", self.store_slug, exc, exc_info=True)

        return items
