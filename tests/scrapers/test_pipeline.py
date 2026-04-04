"""Tests for the scrape result pipeline — normalise + upsert with dedup."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.scrapers.base import ScrapedItem
from app.scrapers.pipeline import process_scrape


@pytest.mark.asyncio
async def test_process_scrape_inserts_prices(
    db_session: AsyncSession,
    mock_store: Store,
    single_scraped_item: ScrapedItem,
) -> None:
    """process_scrape should insert new Price records."""
    count = await process_scrape(
        store_slug="test-store",
        items=[single_scraped_item],
        db=db_session,
    )
    assert count == 1

    # Verify price was persisted
    result = await db_session.execute(select(Price))
    prices = list(result.scalars().all())
    assert len(prices) == 1
    assert prices[0].price == Decimal("2.49")


@pytest.mark.asyncio
async def test_process_scrape_creates_product(
    db_session: AsyncSession,
    mock_store: Store,
    single_scraped_item: ScrapedItem,
) -> None:
    """process_scrape should create a new Product when none exists."""
    await process_scrape(
        store_slug="test-store",
        items=[single_scraped_item],
        db=db_session,
    )

    result = await db_session.execute(select(Product))
    products = list(result.scalars().all())
    assert len(products) == 1
    assert products[0].barcode == "5901234123457"
    assert products[0].status == ProductStatus.PENDING_REVIEW


@pytest.mark.asyncio
async def test_process_scrape_dedup_same_day(
    db_session: AsyncSession,
    mock_store: Store,
    single_scraped_item: ScrapedItem,
) -> None:
    """process_scrape should skip duplicate prices on the same day."""
    # First run
    count1 = await process_scrape(
        store_slug="test-store",
        items=[single_scraped_item],
        db=db_session,
    )
    assert count1 == 1

    # Second run — same day, should be deduplicated
    count2 = await process_scrape(
        store_slug="test-store",
        items=[single_scraped_item],
        db=db_session,
    )
    assert count2 == 0

    # Only one price in the database
    result = await db_session.execute(select(Price))
    prices = list(result.scalars().all())
    assert len(prices) == 1


@pytest.mark.asyncio
async def test_process_scrape_multiple_items(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """process_scrape should handle multiple items in one batch."""
    items = [
        ScrapedItem(
            name="Product A",
            price=Decimal("1.00"),
            barcode="AAA111",
            source="web",
        ),
        ScrapedItem(
            name="Product B",
            price=Decimal("2.00"),
            barcode="BBB222",
            source="web",
        ),
    ]
    count = await process_scrape(
        store_slug="test-store",
        items=items,
        db=db_session,
    )
    assert count == 2


@pytest.mark.asyncio
async def test_process_scrape_reuses_existing_product_by_barcode(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """process_scrape should reuse a product matched by barcode."""
    # Pre-create product
    product = Product(
        name="Existing Product",
        slug="existing-product",
        barcode="REUSE123",
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.commit()

    item = ScrapedItem(
        name="Renamed Product",  # different name, same barcode
        price=Decimal("5.00"),
        barcode="REUSE123",
        source="web",
    )
    count = await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )
    assert count == 1

    # Should not have created a new product
    result = await db_session.execute(select(Product))
    products = list(result.scalars().all())
    assert len(products) == 1
    assert products[0].name == "Existing Product"  # not overwritten


@pytest.mark.asyncio
async def test_process_scrape_reuses_existing_product_by_name(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """process_scrape should reuse a product matched by normalised name."""
    product = Product(
        name="Unique Name",
        slug="unique-name",
        status=ProductStatus.ACTIVE,
    )
    db_session.add(product)
    await db_session.commit()

    item = ScrapedItem(
        name="Unique Name",
        price=Decimal("3.00"),
        source="web",
    )
    count = await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )
    assert count == 1

    result = await db_session.execute(select(Product))
    products = list(result.scalars().all())
    assert len(products) == 1


@pytest.mark.asyncio
async def test_process_scrape_unknown_store_raises(
    db_session: AsyncSession,
    single_scraped_item: ScrapedItem,
) -> None:
    """process_scrape should raise ValueError for unknown store slug."""
    with pytest.raises(ValueError, match="Store not found"):
        await process_scrape(
            store_slug="nonexistent",
            items=[single_scraped_item],
            db=db_session,
        )


@pytest.mark.asyncio
async def test_process_scrape_brochure_source(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """process_scrape should correctly map brochure source."""
    item = ScrapedItem(
        name="Brochure Item",
        price=Decimal("4.00"),
        source="brochure",
    )
    count = await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )
    assert count == 1

    result = await db_session.execute(select(Price))
    price = result.scalars().first()
    assert price is not None
    assert price.source == "brochure"
