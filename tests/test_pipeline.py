"""Tests for the scrape result pipeline (app/scrapers/pipeline.py).

Covers:
- New item creates a product + price record.
- Second scrape of the same item on the same day is skipped (duplicate guard).
- Brand normalisation is called and its result is stored on the Price.
- Unknown store slug raises ValueError.

All DB interaction uses an in-memory aiosqlite engine created per test so
there is no dependency on a running PostgreSQL instance.  Playwright, httpx,
and Ollama are never called.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models.price import Price, PriceSource
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.scrapers.base import ScrapedItem
from app.scrapers.pipeline import process_scrape

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an in-memory aiosqlite session with all tables created.

    BaseModel.id uses ``default=uuid.uuid4`` (Python-side) so no PostgreSQL
    functions are needed — the ORM generates the UUID before INSERT.

    Yields:
        AsyncSession: A fully initialised async session backed by aiosqlite.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def store(db_session: AsyncSession) -> Store:
    """Insert and return a test Store row.

    Args:
        db_session: The in-memory database session.

    Returns:
        A persisted Store instance with slug 'teststore'.
    """
    s = Store(
        id=uuid.uuid4(),
        name="Test Store",
        slug="teststore",
    )
    db_session.add(s)
    await db_session.flush()
    return s


def _make_item(
    name: str = "Olive Oil",
    price: Decimal = Decimal("3.99"),
    barcode: str | None = None,
    source: str = "web",
    raw: dict | None = None,
) -> ScrapedItem:
    """Build a ScrapedItem with sensible defaults.

    Args:
        name: Product display name.
        price: Observed price.
        barcode: Optional barcode string.
        source: Scrape source — 'web' or 'brochure'.
        raw: Optional raw dictionary (for brand, discount, etc.).

    Returns:
        A ScrapedItem ready to pass to process_scrape.
    """
    return ScrapedItem(
        name=name,
        price=price,
        currency="EUR",
        barcode=barcode,
        source=source,
        raw=raw or {},
    )


# ---------------------------------------------------------------------------
# Helper — patch brand normalisation to return input unchanged by default
# ---------------------------------------------------------------------------

_BRAND_PATCH = "app.scrapers.pipeline.normalise_brand"


# ---------------------------------------------------------------------------
# Tests: unknown store
# ---------------------------------------------------------------------------


class TestUnknownStore:
    """process_scrape raises ValueError for an unrecognised store slug."""

    async def test_unknown_store_raises_value_error(
        self, db_session: AsyncSession
    ) -> None:
        """A store slug that does not exist in the DB must raise ValueError."""
        item = _make_item()
        with pytest.raises(ValueError, match="Store not found"):
            await process_scrape("no-such-store", [item], db_session)


# ---------------------------------------------------------------------------
# Tests: new item creates product and price
# ---------------------------------------------------------------------------


class TestNewItemInsert:
    """A first scrape of an item creates both a Product and a Price record."""

    async def test_new_item_creates_price_record(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """process_scrape inserts one Price for a brand-new product."""
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            count = await process_scrape("teststore", [_make_item()], db_session)

        assert count == 1

    async def test_new_item_creates_product_row(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """A Product row is persisted with pending_review status."""
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [_make_item(name="Butter")], db_session)

        result = await db_session.execute(
            select(Product).where(Product.name == "Butter")
        )
        product = result.scalars().first()
        assert product is not None
        assert product.status == ProductStatus.PENDING_REVIEW

    async def test_price_record_has_correct_fields(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """The inserted Price row carries the price, currency, and source."""
        item = _make_item(price=Decimal("2.49"), source="brochure")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.price == Decimal("2.49")
        assert price_row.currency == "EUR"
        assert price_row.source == PriceSource.BROCHURE

    async def test_price_linked_to_correct_store(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """The Price row references the store found by slug lookup."""
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [_make_item()], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.store_id == store.id

    async def test_multiple_items_all_inserted(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """All items in a batch are inserted when none are duplicates."""
        items = [
            _make_item(name="Milk", price=Decimal("1.20")),
            _make_item(name="Bread", price=Decimal("0.80")),
            _make_item(name="Eggs", price=Decimal("2.50")),
        ]
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            count = await process_scrape("teststore", items, db_session)

        assert count == 3


# ---------------------------------------------------------------------------
# Tests: duplicate guard
# ---------------------------------------------------------------------------


class TestDuplicateGuard:
    """Second scrape of the same product+store on the same day is skipped."""

    async def test_duplicate_same_day_is_skipped(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """A second identical scrape on the same day inserts 0 new rows."""
        item = _make_item(name="Rice")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            first = await process_scrape("teststore", [item], db_session)
            second = await process_scrape("teststore", [item], db_session)

        assert first == 1
        assert second == 0

    async def test_duplicate_guard_does_not_create_extra_price_rows(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """After two scrapes of the same item today, exactly one Price exists."""
        item = _make_item(name="Sugar")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        prices = result.scalars().all()
        assert len(prices) == 1

    async def test_duplicate_guard_checks_per_store(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """The same product scraped from two different stores gets two Price rows."""
        # Insert a second store
        store2 = Store(id=uuid.uuid4(), name="Other Store", slug="otherstore")
        db_session.add(store2)
        await db_session.flush()

        item = _make_item(name="Flour")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            count1 = await process_scrape("teststore", [item], db_session)
            count2 = await process_scrape("otherstore", [item], db_session)

        assert count1 == 1
        assert count2 == 1

    async def test_duplicate_guard_uses_today_boundary(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """A price recorded yesterday is NOT counted as a duplicate today."""
        item = _make_item(name="Cheese")
        # Insert a price row with yesterday's timestamp directly
        product = Product(
            id=uuid.uuid4(),
            name="Cheese",
            slug="cheese",
            status=ProductStatus.ACTIVE,
        )
        db_session.add(product)
        await db_session.flush()

        yesterday = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
        old_price = Price(
            id=uuid.uuid4(),
            product_id=product.id,
            store_id=store.id,
            price=Decimal("4.00"),
            currency="EUR",
            source=PriceSource.WEB,
            recorded_at=yesterday,
        )
        db_session.add(old_price)
        await db_session.flush()

        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            count = await process_scrape("teststore", [item], db_session)

        # A new row should be inserted because yesterday's price is outside today
        assert count == 1


# ---------------------------------------------------------------------------
# Tests: brand normalisation
# ---------------------------------------------------------------------------


class TestBrandNormalisation:
    """Brand normalisation is called for each item and its result is stored."""

    async def test_normalise_brand_is_called(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """normalise_brand is invoked during pipeline processing."""
        item = _make_item(raw={"brand": "Acme Co."})
        mock_normalise = AsyncMock(return_value="Acme")

        with patch(_BRAND_PATCH, new=mock_normalise):
            await process_scrape("teststore", [item], db_session)

        mock_normalise.assert_called_once()

    async def test_normalised_brand_stored_on_price(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """The canonical brand from normalise_brand is persisted on the Price row."""
        item = _make_item(raw={"brand": "acme co"})
        with patch(_BRAND_PATCH, new=AsyncMock(return_value="Acme")):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.brand == "Acme"

    async def test_none_brand_when_raw_has_no_brand_key(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """Price.brand is None when the raw dict has no 'brand' key."""
        item = _make_item(raw={})
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.brand is None

    async def test_discount_fields_stored_from_raw(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """original_price and discount_percent are taken from raw and stored."""
        item = _make_item(
            raw={
                "original_price": "5.00",
                "discount_percent": 20,
            }
        )
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.original_price == Decimal("5.00")
        assert price_row.discount_percent == 20


# ---------------------------------------------------------------------------
# Tests: source mapping
# ---------------------------------------------------------------------------


class TestSourceMapping:
    """_map_source produces the correct PriceSource enum value."""

    async def test_web_source_mapped_correctly(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """Source 'web' is stored as PriceSource.WEB."""
        item = _make_item(source="web")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.source == PriceSource.WEB

    async def test_brochure_source_mapped_correctly(
        self, db_session: AsyncSession, store: Store
    ) -> None:
        """Source 'brochure' is stored as PriceSource.BROCHURE."""
        item = _make_item(source="brochure")
        with patch(_BRAND_PATCH, new=AsyncMock(return_value=None)):
            await process_scrape("teststore", [item], db_session)

        result = await db_session.execute(select(Price))
        price_row = result.scalars().first()
        assert price_row is not None
        assert price_row.source == PriceSource.BROCHURE
