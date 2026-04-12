"""Generic LLM-powered brochure scraper — works for any grocery store.

A single scraper class replaces all store-specific scrapers.

Phase 1 — Playwright renders the brochure listing page, discovers the
           brochure URL (direct PDF or interactive viewer).

Phase 2 — Pages are processed one-by-one: screenshot → Gemma 4 vision
           extraction → log items immediately → advance to next page.
           Navigation uses a tiered strategy:
             Tier 1: known CSS selectors
             Tier 2: keyboard ArrowRight
             Tier 3: right-side viewport click (works on most flipbooks)
             Tier 4: LLM vision identifies the next-page button coordinates

Store config lives entirely in the ``stores`` table (``brochure_url`` column).
Adding a new store requires only a DB row — no Python code.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_NAV_TIMEOUT = 30_000        # Playwright navigation timeout (ms)
_PAGE_WAIT_MS = 2_000        # extra wait after DOM ready for JS rendering (ms)
_TURN_WAIT_MS = 1_000        # wait after advancing a viewer page (ms)
_SCREENSHOT_TIMEOUT = 10     # seconds — asyncio guard per screenshot
_MAX_LINKS = 300             # max links sent to LLM for text-mode discovery
_MAX_VIEWER_PAGES = 60       # maximum brochure pages to process
_MAX_STUCK_RETRIES = 3       # consecutive same-hash pages before giving up
_LLM_CLICK_CONFIDENCE = 0.3  # minimum confidence to trust LLM click coords
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}

# Regex that matches URLs with a section index suffix like /ar/0 or /ar/0/page/1
_AR_SECTION_RE = re.compile(r"^(.*?/ar/)(\d+)(.*)$")
_MAX_SECTIONS = 10  # safety cap on ar/N section traversal


def _next_section_url(url: str) -> str | None:
    """Return the next ar/N section URL, or None if the pattern is not present.

    Lidl splits its weekly brochure into numbered sections in the URL path:
    ``/ar/0``, ``/ar/1``, etc.  This helper increments the section index so
    the scraper can continue into the next section after exhausting the current one.

    Args:
        url: Current viewer URL.

    Returns:
        URL with section index incremented, or ``None`` if not applicable.
    """
    m = _AR_SECTION_RE.match(url)
    if m:
        return f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}"
    return None


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

_LLM_NAV_SYSTEM_PROMPT = (
    "You are a UI navigator. Given a screenshot of an interactive brochure or "
    "flipbook viewer, locate the NEXT PAGE button or clickable arrow. "
    "Respond ONLY with valid JSON — no markdown, no explanation:\n"
    '{"x": <pixel_x_int>, "y": <pixel_y_int>, "confidence": <float_0_to_1>}\n'
    "If no next-page control is visible or you are uncertain, respond:\n"
    '{"x": null, "y": null, "confidence": 0}'
)


def _llm_find_next_button(
    shot_b64: str,
    llm: Any,
) -> dict[str, int] | None:
    """Ask Gemma 4 where to click to advance to the next viewer page.

    Sends the screenshot directly to the Ollama /api/chat endpoint using the
    same httpx client as OllamaVisionClient.extract_from_image.

    Args:
        shot_b64: Base64-encoded JPEG screenshot.
        llm: OllamaVisionClient instance.

    Returns:
        ``{"x": int, "y": int}`` if a high-confidence button is found,
        else ``None``.
    """
    payload = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": _LLM_NAV_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Where should I click to go to the next page?",
                "images": [shot_b64],
            },
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096},
    }
    try:
        resp = llm._client.post(f"{llm.host}/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        data = json.loads(content)
        x, y = data.get("x"), data.get("y")
        confidence = float(data.get("confidence", 0))
        if x is not None and y is not None and confidence >= _LLM_CLICK_CONFIDENCE:
            logger.info(
                "LLM suggested click at (%d, %d) confidence=%.2f", x, y, confidence
            )
            return {"x": int(x), "y": int(y)}
    except Exception as exc:  # noqa: BLE001
        logger.debug("LLM nav query failed: %s", exc)
    return None


async def _advance_page(
    page: Any,
    shot_bytes: bytes,
    llm: Any,
    stuck_count: int,
) -> None:
    """Attempt to advance the viewer to the next page using tiered strategies.

    Args:
        page: Active Playwright ``Page`` object.
        shot_bytes: Raw bytes of the current screenshot (for LLM vision).
        llm: OllamaVisionClient instance.
        stuck_count: How many consecutive unchanged screenshots we've seen.
    """
    # Tier 1: CSS selectors
    for selector in _NEXT_PAGE_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=300):
                await btn.click()
                return
        except Exception:  # noqa: BLE001
            continue

    # Tier 2: keyboard ArrowRight (works in most flipbook viewers)
    await page.keyboard.press("ArrowRight")

    # Tier 3 (stuck once): click right-centre of viewport
    if stuck_count >= 1:
        vw = _VIEWPORT["width"]
        vh = _VIEWPORT["height"]
        await page.mouse.click(int(vw * 0.75), vh // 2)
        logger.debug("Tier 3: clicked viewport right-centre")

    # Tier 4 (stuck twice): ask LLM where the next-page button is
    if stuck_count >= 2:
        shot_b64 = base64.b64encode(shot_bytes).decode()
        coords = _llm_find_next_button(shot_b64, llm)
        if coords:
            await page.mouse.click(coords["x"], coords["y"])
            logger.debug("Tier 4: LLM click at (%d, %d)", coords["x"], coords["y"])


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
    # Public entry point — overrides BaseScraper.run()
    # ------------------------------------------------------------------

    async def run(self) -> list[ScrapedItem]:
        """Stream brochure pages: discover URL, screenshot each page, extract.

        Overrides the default ``fetch → parse`` pipeline so that LLM extraction
        runs immediately after each page screenshot instead of after all pages
        are collected.  This gives early log feedback and avoids holding large
        lists of base64 images in memory.

        Returns:
            Normalised list of :class:`~app.scrapers.base.ScrapedItem` objects.
        """
        from app.config import get_settings

        settings = get_settings()

        if not settings.LLM_PARSER_ENABLED:
            logger.info(
                "%s: LLM_PARSER_ENABLED=false — skipping run", self.store_slug
            )
            return []

        # Phase 1 — discover the brochure entry point
        raw = await self.fetch()
        if not raw:
            return []

        entry = raw[0]
        pdf_url: str = entry.get("pdf_url", "")
        viewer_url: str = entry.get("viewer_url", "")

        from app.scrapers.llm_parser import (
            LLMBrochureItem,
            OllamaVisionClient,
            llm_items_to_scraped,
            parse_pdf_with_llm,
        )

        llm = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        if not llm.is_available():
            logger.warning(
                "%s: Ollama not available — skipping run", self.store_slug
            )
            return []

        # Legacy PDF path
        if pdf_url:
            llm_items = parse_pdf_with_llm(
                pdf_url,
                store_slug=self.store_slug,
                dpi=settings.LLM_PAGE_DPI,
                client=llm,
            )
            return [self.normalise(i) for i in llm_items_to_scraped(llm_items)]

        if not viewer_url:
            return []

        # Phase 2 — stream page-by-page through the viewer (with ar/N section support)
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "%s: playwright not installed — run: "
                "uv run playwright install chromium --with-deps",
                self.store_slug,
            )
            return []

        all_items: list[ScrapedItem] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
            )
            page = await context.new_page()

            current_url = viewer_url
            section = 0
            global_page_num = 0

            try:
                while current_url:
                    section_had_pages = False
                    try:
                        async for _local_page, b64 in self._iter_viewer_pages(
                            page, current_url, llm
                        ):
                            section_had_pages = True
                            global_page_num += 1
                            try:
                                raw_items: list[LLMBrochureItem] = llm.extract_from_image(
                                    b64, page_num=global_page_num
                                )
                                scraped = llm_items_to_scraped(raw_items)
                                all_items.extend(scraped)
                                logger.info(
                                    "%s: page %d → %d item(s) (total: %d)",
                                    self.store_slug,
                                    global_page_num,
                                    len(scraped),
                                    len(all_items),
                                )
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "%s: page %d extraction error: %s",
                                    self.store_slug, global_page_num, exc,
                                )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "%s: section %d streaming error: %s",
                            self.store_slug, section, exc,
                        )

                    # Advance to next ar/N section if the URL supports it
                    next_url = _next_section_url(current_url)
                    if next_url and section_had_pages and section < _MAX_SECTIONS:
                        section += 1
                        logger.info(
                            "%s: advancing to section %d → %s",
                            self.store_slug, section, next_url,
                        )
                        current_url = next_url
                    else:
                        break
            finally:
                await browser.close()

        logger.info(
            "%s: scrape complete — %d item(s) from viewer",
            self.store_slug, len(all_items),
        )
        return [self.normalise(item) for item in all_items]

    # ------------------------------------------------------------------
    # Phase 1 — brochure URL discovery
    # ------------------------------------------------------------------

    async def fetch(self) -> list[dict[str, Any]]:
        """Discover the current brochure URL.

        Discovery strategy (tried in order):
        1. Playwright renders the listing page.
        2. Direct ``.pdf`` links in DOM → use immediately.
        3. LLM text analysis of all page links → picks brochure URL.
        4. Screenshot fallback → LLM vision identifies the viewer URL.

        Returns:
            List with one entry:
            ``{"pdf_url": str, "title": str}`` **or**
            ``{"viewer_url": str, "title": str}``.
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
                    wait_until="domcontentloaded",
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

                # Strategy 1a — direct .pdf links in the DOM
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

                if not brochure_url:
                    # Strategy 1b — iframe viewer embeds (e.g. Publitas embedded brochure)
                    iframe_srcs: list[str] = await page.evaluate(
                        "() => Array.from(document.querySelectorAll('iframe[src]'))"
                        ".map(f => f.src)"
                        ".filter(s => s.startsWith('http'))"
                    )
                    viewer_hosts = (
                        "publitas.com", "flippingbook.com", "issuu.com",
                        "fliphtml5.com", "yumpu.com",
                    )
                    for src in iframe_srcs:
                        if any(h in src for h in viewer_hosts):
                            # Strip embed query params — use the clean viewer URL
                            brochure_url = src.split("?")[0].rstrip("/") + "/"
                            logger.info(
                                "%s: iframe viewer found → %s",
                                self.store_slug, brochure_url,
                            )
                            break

                if not brochure_url:
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
                                "%s: all discovery strategies exhausted — no brochure found",
                                self.store_slug,
                            )

                if not brochure_url:
                    return []

                if brochure_url.lower().endswith(".pdf"):
                    logger.info(
                        "%s: direct PDF → %s", self.store_slug, brochure_url
                    )
                    return [{"pdf_url": brochure_url, "title": page_title}]

                logger.info(
                    "%s: viewer URL → %s", self.store_slug, brochure_url
                )
                return [{"viewer_url": brochure_url, "title": page_title}]

            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: fetch error: %s", self.store_slug, exc)
                return []
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Phase 2 helpers — viewer iteration
    # ------------------------------------------------------------------

    async def _iter_viewer_pages(
        self,
        page: Any,
        viewer_url: str,
        llm: Any,
    ) -> AsyncIterator[tuple[int, str]]:
        """Navigate a brochure viewer and yield (page_num, base64_jpeg) per page.

        Uses ``domcontentloaded`` for faster navigation on SPA-based viewers.
        Each screenshot is guarded by an asyncio timeout so the loop cannot
        hang indefinitely.  Page advancement uses a tiered strategy: CSS
        selectors → ArrowRight → right-side click → LLM vision click.

        Args:
            page: Active Playwright ``Page`` object.
            viewer_url: URL of the interactive brochure viewer.
            llm: OllamaVisionClient for Tier 4 (LLM navigation fallback).

        Yields:
            ``(page_num, b64_jpeg)`` tuples, 1-indexed.
        """
        await page.goto(
            viewer_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT
        )
        await page.wait_for_timeout(_PAGE_WAIT_MS)

        prev_hash = ""
        stuck_count = 0
        page_num = 0

        for _ in range(_MAX_VIEWER_PAGES + _MAX_STUCK_RETRIES):
            # Take screenshot with timeout guard
            try:
                shot_bytes: bytes = await asyncio.wait_for(
                    page.screenshot(type="jpeg", quality=80, full_page=False),
                    timeout=_SCREENSHOT_TIMEOUT,
                )
            except TimeoutError:
                logger.warning(
                    "%s: screenshot timeout after %ds — stopping",
                    self.store_slug, _SCREENSHOT_TIMEOUT,
                )
                break

            current_hash = hashlib.md5(shot_bytes).hexdigest()  # noqa: S324

            if current_hash == prev_hash:
                stuck_count += 1
                logger.info(
                    "%s: page %d hash unchanged (stuck %d/%d)",
                    self.store_slug, page_num + 1, stuck_count, _MAX_STUCK_RETRIES,
                )
                if stuck_count >= _MAX_STUCK_RETRIES:
                    logger.info(
                        "%s: %d consecutive unchanged pages — end of brochure",
                        self.store_slug, stuck_count,
                    )
                    break
            else:
                stuck_count = 0
                prev_hash = current_hash
                page_num += 1
                yield page_num, base64.b64encode(shot_bytes).decode()
                if page_num >= _MAX_VIEWER_PAGES:
                    logger.info(
                        "%s: reached max %d pages", self.store_slug, _MAX_VIEWER_PAGES
                    )
                    break

            # Advance to next page (tiered strategy)
            await _advance_page(page, shot_bytes, llm, stuck_count)
            await page.wait_for_timeout(_TURN_WAIT_MS)

        logger.info(
            "%s: viewer iteration complete — %d page(s) processed",
            self.store_slug, page_num,
        )

    # ------------------------------------------------------------------
    # Legacy PDF parse (kept for stores with real PDF URLs)
    # ------------------------------------------------------------------

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Extract product offers from a PDF brochure (legacy path only).

        This method handles ``{"pdf_url": str}`` entries when the caller uses
        the default ``BaseScraper.run()`` directly.  In normal operation
        :meth:`run` handles both PDF and viewer paths.

        Args:
            raw: Output of :meth:`fetch` — only ``{"pdf_url": str}`` entries
                 are handled here.

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
            pdf_url: str = entry.get("pdf_url", "")
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
                    items.extend(llm_items_to_scraped(llm_items))
                else:
                    brochure_items = parse_pdf_brochure(
                        pdf_url, store_slug=self.store_slug
                    )
                    items.extend(brochure_items_to_scraped(brochure_items))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%s: PDF parse error (%s): %s", self.store_slug, pdf_url, exc
                )

        return items
