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


@pytest.mark.asyncio
async def test_process_scrape_barcode_match_over_name(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """Barcode match must take priority over name match.

    When a product with barcode X already exists under a different name,
    scraping a renamed item with the same barcode should reuse the existing
    product — it must NOT fall through to name matching and create a duplicate.
    """
    existing = Product(
        name="Original Name",
        slug="original-name",
        barcode="BARCODE999",
        status=ProductStatus.ACTIVE,
    )
    db_session.add(existing)
    await db_session.commit()

    # Item arrives with same barcode but completely different name
    item = ScrapedItem(
        name="Completely Different Name",
        price=Decimal("7.77"),
        barcode="BARCODE999",
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
    # Only the original product should exist — no new product created
    assert len(products) == 1
    assert products[0].name == "Original Name"


@pytest.mark.asyncio
async def test_process_scrape_new_product_has_pending_review_status(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """Auto-created products must start with PENDING_REVIEW status."""
    item = ScrapedItem(
        name="Brand New Item",
        price=Decimal("9.99"),
        source="web",
    )
    await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )

    result = await db_session.execute(select(Product))
    product = result.scalars().first()
    assert product is not None
    assert product.status == ProductStatus.PENDING_REVIEW


@pytest.mark.asyncio
async def test_process_scrape_new_product_slug_generated(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """Auto-created product should receive a non-empty slug."""
    item = ScrapedItem(
        name="Slug Test Product",
        price=Decimal("1.11"),
        source="web",
    )
    await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )

    result = await db_session.execute(select(Product))
    product = result.scalars().first()
    assert product is not None
    assert product.slug != ""
    assert " " not in product.slug


@pytest.mark.asyncio
async def test_process_scrape_barcode_appended_to_slug(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """When barcode is present the last 4 digits must appear in the new product slug."""
    item = ScrapedItem(
        name="Barcode Slug Item",
        price=Decimal("3.33"),
        barcode="9876543210",
        source="web",
    )
    await process_scrape(
        store_slug="test-store",
        items=[item],
        db=db_session,
    )

    result = await db_session.execute(select(Product))
    product = result.scalars().first()
    assert product is not None
    assert "3210" in product.slug


@pytest.mark.asyncio
async def test_process_scrape_unknown_store_error_message(
    db_session: AsyncSession,
    single_scraped_item: ScrapedItem,
) -> None:
    """ValueError for unknown slug should mention the offending slug."""
    with pytest.raises(ValueError, match="bad-slug"):
        await process_scrape(
            store_slug="bad-slug",
            items=[single_scraped_item],
            db=db_session,
        )


@pytest.mark.asyncio
async def test_process_scrape_empty_items_returns_zero(
    db_session: AsyncSession,
    mock_store: Store,
) -> None:
    """process_scrape with an empty item list should return 0 without error."""
    count = await process_scrape(
        store_slug="test-store",
        items=[],
        db=db_session,
    )
    assert count == 0


@pytest.mark.asyncio
async def test_process_scrape_dedup_second_call_returns_zero(
    db_session: AsyncSession,
    mock_store: Store,
    single_scraped_item: ScrapedItem,
) -> None:
    """A second call for the same item on the same day must return 0 inserted."""
    await process_scrape(store_slug="test-store", items=[single_scraped_item], db=db_session)
    count = await process_scrape(store_slug="test-store", items=[single_scraped_item], db=db_session)
    assert count == 0
