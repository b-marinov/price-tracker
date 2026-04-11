"""Integration tests for the full scraper run() pipeline.

Covers the end-to-end flow:
  BaseScraper.run() -> process_scrape() -> ScrapeRun records

No live HTTP calls and no live database — uses the shared in-memory SQLite
fixtures from tests/scrapers/conftest.py.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun, ScrapeStatus
from app.models.store import Store
from app.scrapers.base import BaseScraper, ScrapedItem
from app.scrapers.pipeline import process_scrape

# ---------------------------------------------------------------------------
# Concrete mock scraper used only inside this module
# ---------------------------------------------------------------------------

class _MockStoreScraper(BaseScraper):
    """A minimal concrete scraper that returns pre-canned items.

    Attributes:
        store_slug: Matches the 'test-store' slug created by the mock_store
            fixture so the pipeline can resolve the store.
        _items: Items returned by fetch/parse/run.
    """

    store_slug: str = "test-store"

    def __init__(self, items: list[ScrapedItem]) -> None:
        """Initialise with a fixed list of pre-built ScrapedItem instances.

        Args:
            items: Items that will be returned by :meth:`run`.
        """
        self._items = items

    async def fetch(self) -> list[dict]:
        """Return an empty list — items are injected directly via parse."""
        return []

    def parse(self, raw: list[dict]) -> list[ScrapedItem]:
        """Return the pre-built items regardless of raw input."""
        return self._items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_items(n: int = 2) -> list[ScrapedItem]:
    """Build a list of n unique normalised ScrapedItem instances.

    Args:
        n: Number of items to generate.

    Returns:
        A list of ScrapedItem objects with unique names and barcodes.
    """
    return [
        ScrapedItem(
            name=f"Product {i}",
            price=Decimal(f"{i}.99"),
            currency="EUR",
            barcode=f"BARCODE{i:04d}",
            source="web",
        )
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_run_returns_normalised_items() -> None:
    """BaseScraper.run() should return all items after fetch+parse+normalise."""
    raw_items = [
        ScrapedItem(name="  raw apple  ", price=Decimal("1.50"), source="web"),
        ScrapedItem(name="  raw banana  ", price=Decimal("0.75"), source="brochure"),
    ]
    scraper = _MockStoreScraper(items=raw_items)
    results = await scraper.run()

    assert len(results) == 2
    assert results[0].name == "Raw Apple"
    assert results[1].name == "Raw Banana"
    # Normalisation should have stripped and title-cased all names
    for r in results:
        assert r.name == r.name.strip()
        assert r.name == r.name.title()


@pytest.mark.asyncio
async def test_full_pipeline_inserts_prices(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """run() items fed into process_scrape() should produce Price rows."""
    items = _make_items(3)
    scraper = _MockStoreScraper(items=items)
    normalised = await scraper.run()

    count = await process_scrape(
        store_slug=mock_store.slug,
        items=normalised,
        db=db_session,
    )
    assert count == 3

    result = await db_session.execute(select(Price))
    prices = list(result.scalars().all())
    assert len(prices) == 3


@pytest.mark.asyncio
async def test_full_pipeline_creates_scrape_run_record(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """A ScrapeRun record should be created and set to COMPLETED after a run.

    This test simulates what the Celery task does around the scraper call:
    1. Create a ScrapeRun with status=RUNNING.
    2. Execute scraper.run() + process_scrape().
    3. Update the ScrapeRun to COMPLETED with items_found set.
    """
    from datetime import datetime

    # --- Step 1: create ScrapeRun (mirrors tasks.py) ---
    scrape_run = ScrapeRun(
        store_id=mock_store.id,
        status=ScrapeStatus.RUNNING,
    )
    db_session.add(scrape_run)
    await db_session.commit()
    await db_session.refresh(scrape_run)

    assert scrape_run.status == ScrapeStatus.RUNNING

    # --- Step 2: run scraper and pipeline ---
    items = _make_items(2)
    scraper = _MockStoreScraper(items=items)
    normalised = await scraper.run()
    inserted = await process_scrape(
        store_slug=mock_store.slug,
        items=normalised,
        db=db_session,
    )

    # --- Step 3: update ScrapeRun (mirrors tasks.py) ---
    scrape_run.status = ScrapeStatus.COMPLETED
    scrape_run.items_found = inserted
    scrape_run.finished_at = datetime.now(UTC)
    await db_session.commit()
    await db_session.refresh(scrape_run)

    # Verify final state
    assert scrape_run.status == ScrapeStatus.COMPLETED
    assert scrape_run.items_found == 2
    assert scrape_run.finished_at is not None
    assert scrape_run.error_msg is None


@pytest.mark.asyncio
async def test_scrape_run_marked_failed_on_error(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """ScrapeRun should be marked FAILED and carry the error message on exception."""
    from datetime import datetime

    scrape_run = ScrapeRun(
        store_id=mock_store.id,
        status=ScrapeStatus.RUNNING,
    )
    db_session.add(scrape_run)
    await db_session.commit()
    await db_session.refresh(scrape_run)

    # Simulate a failure during scraping
    try:
        raise RuntimeError("HTTP 503 from upstream")
    except Exception as exc:
        scrape_run.status = ScrapeStatus.FAILED
        scrape_run.error_msg = str(exc)[:2000]
        scrape_run.finished_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(scrape_run)

    assert scrape_run.status == ScrapeStatus.FAILED
    assert scrape_run.error_msg == "HTTP 503 from upstream"
    assert scrape_run.finished_at is not None


@pytest.mark.asyncio
async def test_full_pipeline_dedup_across_two_runs(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """Running the same scraper twice on the same day must not insert duplicates."""
    items = _make_items(2)
    scraper = _MockStoreScraper(items=items)

    normalised = await scraper.run()
    first_count = await process_scrape(
        store_slug=mock_store.slug,
        items=normalised,
        db=db_session,
    )
    second_count = await process_scrape(
        store_slug=mock_store.slug,
        items=normalised,
        db=db_session,
    )

    assert first_count == 2
    assert second_count == 0

    result = await db_session.execute(select(Price))
    assert len(list(result.scalars().all())) == 2


@pytest.mark.asyncio
async def test_full_pipeline_products_created_with_correct_metadata(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """Auto-created products should capture barcode, name, and pending status."""
    items = [
        ScrapedItem(
            name="Organic Yoghurt",
            price=Decimal("2.20"),
            barcode="9990001234567",
            source="web",
        )
    ]
    scraper = _MockStoreScraper(items=items)
    normalised = await scraper.run()
    await process_scrape(
        store_slug=mock_store.slug,
        items=normalised,
        db=db_session,
    )

    result = await db_session.execute(select(Product))
    product = result.scalars().first()
    assert product is not None
    assert product.name == "Organic Yoghurt"
    assert product.barcode == "9990001234567"
    assert product.status == ProductStatus.PENDING_REVIEW
