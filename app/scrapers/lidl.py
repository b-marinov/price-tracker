"""Lidl Bulgaria brochure scraper.

Lidl Bulgaria hosts its weekly brochure as a JavaScript-rendered viewer at:
    https://www.lidl.bg/l/bg/broshura/{date-range}/view/flyer/page/1

The date-range segment changes weekly (format: DD-MM-DD-MM, e.g. 30-03-26-04).
Because the viewer is fully JS-rendered, the PDF URL cannot be extracted with
a simple HTTP request.

Current status: REQUIRES_PLAYWRIGHT
    This scraper returns 0 items until Playwright (or an equivalent headless
    browser tool) is integrated into the stack.  When that is available, the
    implementation should:
        1. Navigate to the current brochure viewer URL.
        2. Intercept the network request for the PDF asset, or click the
           download button to obtain the PDF URL.
        3. Parse the PDF with app.scrapers.pdf_parser.parse_pdf_brochure().

Tracking issue: add 'lidl-playwright' GitHub issue when ready to implement.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


class LidlScraper(BaseScraper):
    """Scraper stub for Lidl Bulgaria.

    Returns 0 items until Playwright support is added.
    See module docstring for the intended implementation approach.
    """

    store_slug: ClassVar[str] = "lidl"

    async def fetch(self) -> list[dict[str, Any]]:
        """Return empty — Lidl brochure viewer requires JS rendering.

        Returns:
            An empty list.
        """
        logger.warning(
            "LidlScraper: the Lidl Bulgaria brochure viewer is fully "
            "JS-rendered and cannot be scraped with httpx alone. "
            "Playwright integration is required. Returning 0 items."
        )
        return []

    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """No-op parse — fetch always returns empty.

        Args:
            raw: Ignored.

        Returns:
            An empty list.
        """
        return []
