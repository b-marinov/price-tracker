"""Shared fixtures for scraper tests."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
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


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine for tests.

    Yields:
        An async engine backed by SQLite.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session that rolls back after each test.

    Yields:
        An AsyncSession connected to the in-memory SQLite database.
    """
    session_factory = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_store_id() -> uuid.UUID:
    """Return a deterministic UUID for test stores."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def mock_store(db_session: AsyncSession, mock_store_id: uuid.UUID) -> Store:
    """Insert and return a test store.

    Returns:
        A Store instance persisted in the test database.
    """
    store = Store(
        id=mock_store_id,
        name="Test Store",
        slug="test-store",
        website_url="https://test-store.example.com",
        active=True,
    )
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)
    return store


@pytest.fixture
def sample_scraped_items() -> list[ScrapedItem]:
    """Return a list of sample ScrapedItem instances for testing."""
    return [
        ScrapedItem(
            name="  мляко прясно  ",
            price=Decimal("2.49"),
            currency="BGN",
            unit="l",
            barcode="5901234123457",
            source="web",
            raw={"original": "milk"},
        ),
        ScrapedItem(
            name="хляб бял  ",
            price=Decimal("1.29"),
            currency="BGN",
            unit="бр",
            barcode="5901234123458",
            source="web",
            raw={"original": "bread"},
        ),
        ScrapedItem(
            name="  кашкавал ",
            price=Decimal("8.99"),
            currency="",
            unit=None,
            barcode=None,
            source="brochure",
            raw={"original": "cheese"},
        ),
    ]


@pytest.fixture
def single_scraped_item() -> ScrapedItem:
    """Return a single normalised ScrapedItem for pipeline tests."""
    return ScrapedItem(
        name="Мляко Прясно",
        price=Decimal("2.49"),
        currency="BGN",
        unit="l",
        barcode="5901234123457",
        source="web",
        raw={},
    )
