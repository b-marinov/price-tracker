"""Generic LLM-powered brochure scraper — works for any grocery store.

A single scraper class replaces all store-specific scrapers.

Phase A — Playwright navigates all brochure pages as fast as possible,
           collecting screenshots.  No LLM calls during navigation —
           GPU stays idle but CPU/network runs at full speed.

Phase B — All screenshots are passed to Gemma 4 for extraction in one
           continuous batch.  GPU runs without interruption.

Navigation uses two tiers only:
  1. ArrowRight keyboard press (works for virtually all flipbook viewers)
  2. Right-centre viewport click (fallback when ArrowRight gets stuck)

Store config lives entirely in the ``stores`` table (``brochure_url`` column).
Adding a new store requires only a DB row — no Python code.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_NAV_TIMEOUT = 30_000        # Playwright navigation timeout (ms)
_PAGE_WAIT_MS = 500          # extra wait after DOM ready for JS rendering (ms)
_TURN_WAIT_MS = 300          # wait after advancing a viewer page (ms)
_SCREENSHOT_TIMEOUT = 10     # seconds — asyncio guard per screenshot
_MAX_LINKS = 300             # max links sent to LLM for text-mode discovery
_MAX_VIEWER_PAGES = 500      # maximum brochure pages to process
_MAX_STUCK_RETRIES = 3       # consecutive same-hash pages before giving up
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



async def _advance_page(
    page: Any,
    stuck_count: int,
) -> None:
    """Attempt to advance the viewer to the next page.

    Strategy (in order):
    1. ArrowRight keyboard press — works on virtually all flipbook viewers.
    2. Right-centre viewport click — fallback for viewers that need a click.

    The CSS-selector tier and LLM-vision tier were removed: they were rarely
    effective and added 3+ seconds of overhead per page (10 selectors × 300 ms
    timeout each, plus an extra LLM inference call when stuck).

    Args:
        page: Active Playwright ``Page`` object.
        stuck_count: How many consecutive unchanged screenshots we've seen.
    """
    # Primary: ArrowRight (works in most flipbook viewers)
    await page.keyboard.press("ArrowRight")

    # Fallback (stuck once): click right-centre of viewport
    if stuck_count >= 1:
        vw = _VIEWPORT["width"]
        vh = _VIEWPORT["height"]
        await page.mouse.click(int(vw * 0.75), vh // 2)
        logger.debug("Fallback click: viewport right-centre (stuck=%d)", stuck_count)


class GenericBrochureScraper(BaseScraper):
    """LLM-powered brochure scraper that works for any grocery store.

    Instantiate with the store's slug and brochure listing URL; no subclassing
    required.  Gemma 4 handles PDF URL discovery and content extraction.

    Attributes:
        store_slug: Unique store slug (shadows the ClassVar per instance).
        brochure_listing_url: URL of the page that lists current brochures.
    """

    store_slug: ClassVar[str] = "generic"  # overridden per instance in __init__

    def __init__(
        self,
        store_slug: str,
        brochure_listing_url: str,
        cancel_checker: Callable[[], None] | None = None,
    ) -> None:
        self.store_slug = store_slug  # type: ignore[misc]
        self.brochure_listing_url = brochure_listing_url
        self._cancel_checker = cancel_checker

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

        # Phase 1 — discover all brochure entry points on the listing page
        raw = await self.fetch()
        if not raw:
            return []

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

        all_items: list[ScrapedItem] = []

        pdf_entries = [e for e in raw if e.get("pdf_url")]
        viewer_entries = [e for e in raw if e.get("viewer_url")]

        logger.info(
            "%s: %d PDF brochure(s), %d viewer brochure(s) discovered",
            self.store_slug, len(pdf_entries), len(viewer_entries),
        )

        # Legacy PDF path — no browser needed
        for entry in pdf_entries:
            pdf_url: str = entry["pdf_url"]
            try:
                llm_items = parse_pdf_with_llm(
                    pdf_url,
                    store_slug=self.store_slug,
                    dpi=settings.LLM_PAGE_DPI,
                    client=llm,
                )
                all_items.extend(llm_items_to_scraped(llm_items))
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: PDF parse error (%s): %s", self.store_slug, pdf_url, exc)

        if not viewer_entries:
            return [self.normalise(i) for i in all_items]

        # Phase 2 — stream page-by-page through each viewer (with ar/N section support)
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "%s: playwright not installed — run: "
                "uv run playwright install chromium --with-deps",
                self.store_slug,
            )
            return [self.normalise(i) for i in all_items]

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
            )
            page = await context.new_page()

            # Phase A — collect screenshots from all brochure sections WITHOUT LLM.
            # The browser navigates as fast as possible; GPU stays idle here.
            # Phase B — LLM runs over the collected screenshots continuously.
            # This keeps GPU busy and avoids interleaving navigation with inference.
            all_screenshots: list[tuple[int, str]] = []  # (global_page_num, b64_jpeg)
            global_page_num = 0

            try:
                for entry_idx, entry in enumerate(viewer_entries):
                    viewer_url: str = entry["viewer_url"]
                    logger.info(
                        "%s: [Phase A] brochure %d/%d → %s",
                        self.store_slug, entry_idx + 1, len(viewer_entries), viewer_url,
                    )

                    current_url = viewer_url
                    section = 0

                    while current_url:
                        if self._cancel_checker:
                            self._cancel_checker()
                        section_had_pages = False
                        try:
                            async for _local_page, b64 in self._iter_viewer_pages(
                                page, current_url
                            ):
                                if self._cancel_checker:
                                    self._cancel_checker()
                                section_had_pages = True
                                global_page_num += 1
                                all_screenshots.append((global_page_num, b64))
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "%s: section %d collection error: %s",
                                self.store_slug, section, exc,
                            )

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
                "%s: [Phase A] complete — %d screenshot(s) collected",
                self.store_slug, len(all_screenshots),
            )

            # Phase B — LLM extraction (GPU runs continuously, no navigation overhead)
            for page_num, b64 in all_screenshots:
                if self._cancel_checker:
                    self._cancel_checker()
                try:
                    raw_items: list[LLMBrochureItem] = llm.extract_from_image(
                        b64, page_num=page_num
                    )
                    scraped = llm_items_to_scraped(raw_items)

                    # Within-page dedup: drop exact (name, price) duplicates
                    seen_on_page: set[tuple[str, str]] = set()
                    deduped: list[ScrapedItem] = []
                    for _it in scraped:
                        key = (_it.name.lower().strip(), str(_it.price))
                        if key not in seen_on_page:
                            seen_on_page.add(key)
                            deduped.append(_it)
                    if len(deduped) < len(scraped):
                        logger.debug(
                            "%s: page %d dedup removed %d duplicate item(s)",
                            self.store_slug, page_num, len(scraped) - len(deduped),
                        )
                    scraped = deduped

                    all_items.extend(scraped)
                    logger.info(
                        "%s: page %d → %d item(s) (total: %d)",
                        self.store_slug, page_num, len(scraped), len(all_items),
                    )
                    for _it in scraped:
                        _brand = _it.raw.get("brand") if _it.raw else None
                        _pack = _it.raw.get("pack_info") if _it.raw else None
                        _unit = _it.unit
                        _size_str = (
                            f" {_pack}" if _pack
                            else f" /{_unit}" if _unit
                            else ""
                        )
                        logger.info(
                            "%s:   + %s%s%s @ %.2f %s",
                            self.store_slug,
                            f"{_brand} " if _brand else "",
                            _it.name,
                            _size_str,
                            float(_it.price),
                            _it.currency,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s: page %d extraction error: %s",
                        self.store_slug, page_num, exc,
                    )

        logger.info(
            "%s: scrape complete — %d item(s) from %d brochure(s)",
            self.store_slug, len(all_items), len(raw),
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

                brochure_urls: list[str] = []

                # Strategy 1a — direct .pdf links in the DOM
                if direct_links:
                    logger.info(
                        "%s: %d direct PDF link(s) in DOM",
                        self.store_slug, len(direct_links),
                    )
                    if len(direct_links) == 1:
                        brochure_urls = [direct_links[0]["href"]]
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
                        brochure_urls = chosen if chosen else [direct_links[0]["href"]]

                if not brochure_urls:
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
                            clean_url = src.split("?")[0].rstrip("/") + "/"
                            brochure_urls.append(clean_url)
                            logger.info(
                                "%s: iframe viewer found → %s",
                                self.store_slug, clean_url,
                            )

                if not brochure_urls:
                    # Strategy 1c — anchor links matching known viewer URL patterns
                    # Catches e.g. Lidl: /l/bg/broshura/<date>/ar/0 without LLM
                    viewer_link_patterns = (
                        "/broshura/", "/brochure/",
                        "publitas.com/", "view.publitas.com/",
                        "flippingbook.com/", "issuu.com/",
                        "fliphtml5.com/", "yumpu.com/",
                    )
                    raw_viewer_links: list[str] = await page.evaluate(
                        "() => Array.from(document.querySelectorAll('a[href]'))"
                        ".map(a => a.href)"
                        ".filter(h => h.startsWith('http'))"
                    )
                    seen_hrefs: set[str] = set()
                    for href in raw_viewer_links:
                        # Skip the listing page itself
                        if href.rstrip("/") == self.brochure_listing_url.rstrip("/"):
                            continue
                        if any(p in href for p in viewer_link_patterns) and href not in seen_hrefs:
                            seen_hrefs.add(href)
                            brochure_urls.append(href)
                            logger.info(
                                "%s: viewer link pattern → %s", self.store_slug, href
                            )

                if not brochure_urls:
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
                        brochure_urls = urls
                        logger.info(
                            "%s: LLM text → %d URL(s)", self.store_slug, len(urls)
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
                            brochure_urls = urls
                            logger.info(
                                "%s: vision → %d URL(s)", self.store_slug, len(urls)
                            )
                        else:
                            logger.warning(
                                "%s: all discovery strategies exhausted — no brochure found",
                                self.store_slug,
                            )

                if not brochure_urls:
                    return []

                results: list[dict[str, str]] = []
                for url in brochure_urls:
                    if url.lower().endswith(".pdf"):
                        logger.info("%s: direct PDF → %s", self.store_slug, url)
                        results.append({"pdf_url": url, "title": page_title})
                    else:
                        logger.info("%s: viewer URL → %s", self.store_slug, url)
                        results.append({"viewer_url": url, "title": page_title})
                return results

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
    ) -> AsyncIterator[tuple[int, str]]:
        """Navigate a brochure viewer and yield (page_num, base64_jpeg) per page.

        Uses ``domcontentloaded`` for faster navigation on SPA-based viewers.
        Each screenshot is guarded by an asyncio timeout so the loop cannot
        hang indefinitely.  Page advancement: ArrowRight primary, right-centre
        click fallback when stuck.

        Args:
            page: Active Playwright ``Page`` object.
            viewer_url: URL of the interactive brochure viewer.

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

            # Advance to next page
            await _advance_page(page, stuck_count)
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
