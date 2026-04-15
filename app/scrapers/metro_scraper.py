"""Metro Bulgaria product listing scraper.

Scrapes the Metro online shop promotions page by scrolling through
the infinite-scroll product grid and extracting structured data from
the DOM.  No LLM is needed — all data is parsed from HTML attributes
and text content.

DOM structure per product card::

    div.sd-articlecard
      .image-container img[src]     — product image
      a.title[description]          — product name (most reliable)
      .bundle.packaging-type.pill   — pack info (e.g. "1 БРОЙ")
      .primary.promotion span       — promo price (EUR and BGN)
      .strike-through span          — original price (EUR and BGN)
      .label-promotion span         — promo labels

Pagination is infinite scroll: scroll to bottom, wait, check for new
cards.  Stops when the count stabilises or hits the safety cap.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)

_NAV_TIMEOUT = 30_000
_PAGE_WAIT_MS = 2_000
_SCROLL_WAIT_MS = 2_500
_MAX_ITEMS = 1_200
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1280, "height": 900}

# Regex to extract a numeric price like "3,56" from text like "3,56 €"
_PRICE_RE = re.compile(r"([\d]+[.,][\d]{1,2})\s*\u20ac")
# Regex to extract article ID from href path segment like BTY-X335615
_ARTICLE_ID_RE = re.compile(r"/(BTY-[A-Z0-9]+)/")

# Metro own-label brand prefixes — checked longest-first so "Metro Chef"
# is matched before the bare "Metro" prefix.
_METRO_OWN_BRANDS: tuple[str, ...] = (
    "Metro Chef",
    "Metro Premium",
    "Metro Quality",
    "Metro",
)

# Trailing weight / volume / count at the end of a Metro product name.
# Examples: 100Г  2КГ  670 Г  6 Х 77 Г  1.5Л  500МЛ  6x100МЛ  2БР
_TRAILING_SIZE_RE = re.compile(
    r"\s+(\d[\d\s,.]*(?:[xXхХ]\s*\d+)?)\s*"
    r"(г(?:р)?|кг|мл|л|бр|пак)\s*$",
    re.IGNORECASE,
)

_UNIT_NORM: dict[str, str] = {
    "г": "г", "гр": "г", "кг": "кг",
    "мл": "мл", "л": "л", "бр": "бр", "пак": "пак",
}


def _parse_name_brand_pack(
    raw_name: str,
    dom_pack_info: str | None,
) -> tuple[str, str | None, str | None]:
    """Split a raw Metro product title into (name, brand, pack_info).

    1. Strip a Metro own-label prefix (Metro Chef / Metro Premium / …).
    2. Strip a trailing size token (100Г, 2Кг, 6 Х 77 Г, …).
    3. Fall back to the DOM pack_info element only when no size was found
       in the name AND the DOM value conveys more than "1 БРОЙ".

    Args:
        raw_name: Full product title from the Metro DOM.
        dom_pack_info: Value of the ``.bundle.packaging-type.pill`` element.

    Returns:
        Tuple of (clean product name, brand or None, pack_info or None).
    """
    name = raw_name.strip()
    brand: str | None = None

    # 1. Detect Metro own-label brand prefix
    upper = name.upper()
    for prefix in _METRO_OWN_BRANDS:
        if upper.startswith(prefix.upper()):
            brand = prefix
            name = name[len(prefix):].lstrip(" -–")
            break

    # 2. Extract trailing size / weight token from the name
    pack_info: str | None = None
    m = _TRAILING_SIZE_RE.search(name)
    if m:
        qty = m.group(1).strip()
        unit = _UNIT_NORM.get(m.group(2).lower(), m.group(2).lower())
        pack_info = f"{qty} {unit}"
        name = name[: m.start()].strip()

    # 3. Fall back to DOM pack_info when it adds real information
    if pack_info is None and dom_pack_info:
        # Skip trivial "1 БРОЙ" — it means nothing useful
        if not re.fullmatch(r"1\s*брой", dom_pack_info, re.IGNORECASE):
            pack_info = dom_pack_info.lower()

    return name or raw_name, brand, pack_info

# JavaScript snippet that extracts all product cards from the DOM.
# Returns a list of plain objects serialisable to Python dicts.
_JS_EXTRACT = """
() => {
    const cards = document.querySelectorAll('.sd-articlecard');
    return Array.from(cards).map(card => {
        const titleEl = card.querySelector('a.title');
        const name = titleEl ? (titleEl.getAttribute('description') || titleEl.textContent || '').trim() : '';
        const href = titleEl ? (titleEl.getAttribute('href') || '') : '';

        const imgEl = card.querySelector('.image-container img');
        const imgSrc = imgEl ? (imgEl.getAttribute('src') || '') : '';

        const packEl = card.querySelector('.bundle.packaging-type.pill');
        const packInfo = packEl ? packEl.textContent.trim() : '';

        // Promo prices (EUR)
        const promoEls = card.querySelectorAll('.primary.promotion span');
        let promoEurText = '';
        promoEls.forEach(el => {
            const t = el.textContent || '';
            if (t.includes('€') && !promoEurText) promoEurText = t.trim();
        });

        // Original / strike-through prices (EUR)
        const strikeEls = card.querySelectorAll('.strike-through span');
        let strikeEurText = '';
        strikeEls.forEach(el => {
            const t = el.textContent || '';
            if (t.includes('€') && !strikeEurText) strikeEurText = t.trim();
        });

        // Promo label
        const labelEl = card.querySelector('.label-promotion span');
        const promoLabel = labelEl ? labelEl.textContent.trim() : '';

        return {
            name: name,
            href: href,
            image_src: imgSrc,
            pack_info: packInfo,
            promo_eur_text: promoEurText,
            strike_eur_text: strikeEurText,
            promo_label: promoLabel
        };
    });
}
"""


def _parse_eur_price(text: str) -> float | None:
    """Extract a EUR price float from text like '3,56 €'.

    Args:
        text: Raw price string from the DOM.

    Returns:
        Price as float, or None if not parseable.
    """
    m = _PRICE_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def _extract_article_id(href: str) -> str | None:
    """Extract the article ID from a product href.

    Args:
        href: Product link path, e.g. '/shop/pv/BTY-X335615/0032/...'.

    Returns:
        Article ID string (e.g. 'BTY-X335615'), or None.
    """
    m = _ARTICLE_ID_RE.search(href)
    return m.group(1) if m else None


def _upgrade_image_url(src: str) -> str:
    """Replace small thumbnail dimensions with larger ones in the image URL.

    Args:
        src: Original image URL with w=144&h=144 or similar.

    Returns:
        URL with w=400&h=400 for better quality.
    """
    if not src:
        return src
    result = re.sub(r"w=\d+", "w=400", src)
    result = re.sub(r"h=\d+", "h=400", result)
    return result


class MetroProductScraper(BaseScraper):
    """Scraper for Metro Bulgaria's online shop promotions page.

    Uses Playwright to scroll through the infinite-scroll product grid
    and extracts structured product data directly from the DOM — no LLM
    required.

    Attributes:
        store_slug: Always ``"metro"``.
        listing_url: URL of the Metro promotions page to scrape.
    """

    store_slug: ClassVar[str] = "metro"

    def __init__(
        self,
        store_slug: str,
        listing_url: str,
        cancel_checker: Callable[[], None] | None = None,
    ) -> None:
        self.store_slug = store_slug  # type: ignore[misc]
        self.listing_url = listing_url
        self._cancel_checker = cancel_checker

    async def run(self) -> list[ScrapedItem]:
        """Scrape the Metro product listing via infinite scroll.

        Opens the listing URL in a headless browser, scrolls to load all
        products, then extracts structured data from the DOM.

        Returns:
            List of normalised :class:`ScrapedItem` objects.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "%s: playwright not installed — run: "
                "uv run playwright install chromium --with-deps",
                self.store_slug,
            )
            return []

        logger.info("%s: starting Metro listing scrape → %s", self.store_slug, self.listing_url)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport=_VIEWPORT,
            )
            page = await context.new_page()

            try:
                await page.goto(
                    self.listing_url,
                    wait_until="domcontentloaded",
                    timeout=_NAV_TIMEOUT,
                )
                await page.wait_for_timeout(_PAGE_WAIT_MS)

                # Scroll to load all products via infinite scroll
                prev_count = 0
                stable_rounds = 0
                max_stable = 3  # stop after 3 rounds with no new items

                for scroll_round in range(1, 200):  # safety cap on scroll rounds
                    if self._cancel_checker:
                        self._cancel_checker()
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(_SCROLL_WAIT_MS)

                    current_count: int = await page.evaluate(
                        "() => document.querySelectorAll('.sd-articlecard').length"
                    )

                    logger.info(
                        "%s: scroll %d — %d card(s) loaded",
                        self.store_slug, scroll_round, current_count,
                    )

                    if current_count >= _MAX_ITEMS:
                        logger.info(
                            "%s: reached safety cap of %d items",
                            self.store_slug, _MAX_ITEMS,
                        )
                        break

                    if current_count == prev_count:
                        stable_rounds += 1
                        if stable_rounds >= max_stable:
                            logger.info(
                                "%s: count stable for %d rounds — all items loaded",
                                self.store_slug, max_stable,
                            )
                            break
                    else:
                        stable_rounds = 0

                    prev_count = current_count

                # Extract all product data from the DOM
                raw_cards: list[dict[str, Any]] = await page.evaluate(_JS_EXTRACT)
                logger.info(
                    "%s: extracted %d raw card(s) from DOM",
                    self.store_slug, len(raw_cards),
                )

            finally:
                await browser.close()

        # Parse raw card dicts into ScrapedItems
        items = self._parse_cards(raw_cards)
        logger.info(
            "%s: scrape complete — %d item(s) parsed",
            self.store_slug, len(items),
        )
        return [self.normalise(item) for item in items]

    def _parse_cards(self, raw_cards: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Convert raw JS-extracted card dicts into ScrapedItem objects.

        Args:
            raw_cards: List of dicts from the JS evaluate call.

        Returns:
            List of ScrapedItem objects with valid prices.
        """
        items: list[ScrapedItem] = []

        for card in raw_cards:
            raw_name: str = card.get("name", "").strip()
            if not raw_name:
                continue

            # Split brand prefix and trailing size out of the raw title
            dom_pack: str | None = card.get("pack_info", "").strip() or None
            name, brand, pack_info = _parse_name_brand_pack(raw_name, dom_pack)

            # Parse promo EUR price (primary)
            promo_price = _parse_eur_price(card.get("promo_eur_text", ""))
            # Parse original / strike-through EUR price
            original_price = _parse_eur_price(card.get("strike_eur_text", ""))

            # Use promo price if available, otherwise original
            price_value = promo_price or original_price
            if price_value is None:
                logger.debug("%s: skipping card with no price: %s", self.store_slug, raw_name)
                continue

            try:
                price_decimal = Decimal(str(price_value))
            except InvalidOperation:
                logger.debug("%s: invalid price for %s: %s", self.store_slug, raw_name, price_value)
                continue

            # Calculate discount percent
            discount_percent: int | None = None
            if promo_price and original_price and original_price > 0:
                discount_percent = round((1 - promo_price / original_price) * 100)

            # Build image URL with upgraded resolution
            image_url = _upgrade_image_url(card.get("image_src", ""))

            # Extract article ID as barcode stand-in
            article_id = _extract_article_id(card.get("href", ""))

            # Promo label as description
            promo_label: str | None = card.get("promo_label", "").strip() or None

            item = ScrapedItem(
                name=name,
                price=price_decimal,
                currency="EUR",
                unit=None,
                image_url=image_url or None,
                barcode=article_id,
                source="metro_listing",
                raw={
                    "brand": brand,
                    "pack_info": pack_info,
                    "additional_info": None,
                    "original_price": original_price,
                    "discount_percent": discount_percent,
                    "description": promo_label,
                    "category": None,
                    "source": "metro_listing",
                },
            )
            items.append(item)

        return items

    # ------------------------------------------------------------------
    # ABC stubs — not used directly; run() overrides the pipeline
    # ------------------------------------------------------------------

    async def fetch(self) -> list[dict[str, Any]]:
        """Stub to satisfy BaseScraper ABC — not used directly.

        The :meth:`run` method handles fetching and parsing in one pass.

        Returns:
            Empty list (use :meth:`run` instead).
        """
        return []

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Stub to satisfy BaseScraper ABC — not used directly.

        The :meth:`run` method handles fetching and parsing in one pass.

        Args:
            raw: Unused raw data list.

        Returns:
            Empty list (use :meth:`run` instead).
        """
        return []
