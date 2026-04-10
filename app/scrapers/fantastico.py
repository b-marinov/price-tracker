"""Fantastico Bulgaria brochure scraper.

Fantastico Bulgaria hosts its weekly brochure via FlippingBook:
    https://online.flippingbook.com/view/{id}/

The FlippingBook ID changes each week and is embedded on:
    https://www.fantastico.bg/brochures  (link to special-offers page)
    https://www.fantastico.bg/special-offers/{title}?id={flipbook_id}

FlippingBook does not expose a public REST API for PDF download, and its
viewer is fully JavaScript-rendered.

Current status: REQUIRES_PLAYWRIGHT
    This scraper returns 0 items until Playwright (or an equivalent headless
    browser tool) is integrated.  When that is available, the implementation
    should:
        1. Navigate to https://www.fantastico.bg/brochures.
        2. Extract the current FlippingBook URL (embedded as an iframe or
           window.location redirect on the special-offers page).
        3. Use Playwright to open the FlippingBook viewer and click the PDF
           download button, or intercept the PDF network request.
        4. Parse the PDF with app.scrapers.pdf_parser.parse_pdf_brochure().

Tracking issue: add 'fantastico-playwright' GitHub issue when ready to implement.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from app.scrapers.base import BaseScraper, ScrapedItem

logger = logging.getLogger(__name__)


class FantasticoScraper(BaseScraper):
    """Scraper stub for Fantastico Bulgaria.

    Returns 0 items until Playwright support is added.
    See module docstring for the intended implementation approach.
    """

    store_slug: ClassVar[str] = "fantastico"

    async def fetch(self) -> list[dict[str, Any]]:
        """Return empty — Fantastico brochure viewer requires JS rendering.

        Returns:
            An empty list.
        """
        logger.warning(
            "FantasticoScraper: the Fantastico Bulgaria brochure is hosted on "
            "FlippingBook (fully JS-rendered) with no public PDF API. "
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
