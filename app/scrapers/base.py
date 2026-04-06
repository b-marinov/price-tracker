"""Abstract base scraper and ScrapedItem dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar


@dataclass
class ScrapedItem:
    """A single price observation scraped from a store.

    Attributes:
        name: Product display name as found on the source.
        price: Observed price as a fixed-point decimal.
        currency: ISO 4217 currency code (default BGN).
        unit: Optional unit descriptor (e.g. "kg", "l", "бр").
        image_url: Optional URL to the product image.
        barcode: Optional EAN / UPC barcode string.
        source: How the item was obtained — "web" or "brochure".
        raw: The original raw data dict for debugging / auditing.
    """

    name: str
    price: Decimal
    currency: str = "BGN"
    unit: str | None = None
    image_url: str | None = None
    barcode: str | None = None
    source: str = "web"  # "web" | "brochure"
    raw: dict[str, Any] = field(default_factory=dict)


class BaseScraper(ABC):
    """Abstract base class that every store scraper must implement.

    Subclasses must set ``store_slug`` as a class variable and provide
    concrete implementations of :meth:`fetch` and :meth:`parse`.

    The default :meth:`normalise` performs lightweight cleanup (whitespace
    stripping, title-casing, currency guarantee).  Subclasses may override
    it for store-specific normalisation.
    """

    store_slug: ClassVar[str]
    """URL-friendly slug identifying the target store."""

    @abstractmethod
    async def fetch(self) -> list[dict[str, Any]]:
        """Fetch raw data from the store source.

        Returns:
            A list of raw dictionaries, one per product / offer.
        """

    @abstractmethod
    def parse(self, raw: list[dict[str, Any]]) -> list[ScrapedItem]:
        """Parse raw dictionaries into structured ScrapedItem instances.

        Args:
            raw: Output of :meth:`fetch`.

        Returns:
            A list of validated ScrapedItem objects.
        """

    def normalise(self, item: ScrapedItem) -> ScrapedItem:
        """Apply default normalisation to a single scraped item.

        * Strips leading/trailing whitespace from the name.
        * Title-cases the name for consistent display.
        * Ensures a currency is set (defaults to BGN).

        Args:
            item: The scraped item to normalise.

        Returns:
            A new ScrapedItem with normalised fields.
        """
        return ScrapedItem(
            name=item.name.strip().title(),
            price=item.price,
            currency=item.currency or "BGN",
            unit=item.unit.strip() if item.unit else None,
            image_url=item.image_url,
            barcode=item.barcode.strip() if item.barcode else None,
            source=item.source,
            raw=item.raw,
        )

    async def run(self) -> list[ScrapedItem]:
        """Execute the full scrape pipeline: fetch -> parse -> normalise.

        Returns:
            A list of normalised ScrapedItem objects.
        """
        raw_data = await self.fetch()
        parsed = self.parse(raw_data)
        return [self.normalise(item) for item in parsed]
