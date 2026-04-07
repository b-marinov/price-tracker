"""Shared fixtures for scraper tests."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import AsyncGenerator

# Set required env vars before any app module is imported.
# These are safe dummy values for the in-memory SQLite test environment.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")
os.environ.setdefault("APP_ENV", "testing")

import pytest
import pytest_asyncio
from sqlalchemy import ColumnDefault, String, StaticPool, TypeDecorator, event
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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


class _UUIDAsString(TypeDecorator):
    """Render UUID as CHAR(36) text for SQLite compatibility.

    The production models use ``postgresql.UUID(as_uuid=True)`` which SQLite
    cannot handle natively.  This decorator stores UUID values as their
    canonical hyphenated string form and converts back on load.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        """Convert a UUID instance to a string for storage.

        Args:
            value: A uuid.UUID, string, or None.
            dialect: The SQLAlchemy dialect (unused).

        Returns:
            A hyphenated UUID string or None.
        """
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: object, dialect: object) -> uuid.UUID | None:
        """Convert a stored string back to a uuid.UUID.

        Args:
            value: The raw string value from the database, or None.
            dialect: The SQLAlchemy dialect (unused).

        Returns:
            A uuid.UUID instance or None.
        """
        if value is None:
            return None
        return uuid.UUID(str(value))


def _patch_uuid_columns(target: object, connection: object, **kwargs: object) -> None:
    """Replace all PG UUID columns with the SQLite-compatible string type.

    Also removes ``server_default`` from the ``id`` column so that
    gen_random_uuid() (a PostgreSQL function) is not emitted against SQLite.
    Instead, a Python-side ``default`` callable is set so the ORM generates
    UUIDs before INSERT without needing the DB function.

    Args:
        target: The table object being created.
        connection: The database connection (unused).
        **kwargs: Extra keyword arguments from the event system (ignored).
    """
    for col in target.columns:
        if isinstance(col.type, PG_UUID):
            col.type = _UUIDAsString()
        if col.name == "id":
            # Remove the PostgreSQL server_default (gen_random_uuid) and supply
            # a proper SQLAlchemy ColumnDefault so the ORM generates UUIDs
            # client-side before INSERT without needing a DB function.
            col.server_default = None
            if col.default is None:
                col.default = ColumnDefault(uuid.uuid4)


@pytest_asyncio.fixture
async def async_engine():
    """Create an in-memory SQLite async engine for tests.

    Patches all PostgreSQL UUID columns to use a string representation and
    removes PostgreSQL-specific server_default functions so that the full
    model set works on SQLite in-memory.

    Yields:
        An async engine backed by SQLite in-memory.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Patch UUID columns and remove PG server functions before DDL is emitted
    for table in Base.metadata.sorted_tables:
        event.listen(table, "before_create", _patch_uuid_columns)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    # Remove listeners so subsequent test sessions start clean
    for table in Base.metadata.sorted_tables:
        event.remove(table, "before_create", _patch_uuid_columns)


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for a single test.

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
    """Return a deterministic UUID for test stores.

    Returns:
        A fixed uuid.UUID used across all store-related fixtures.
    """
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def mock_store(db_session: AsyncSession, mock_store_id: uuid.UUID) -> Store:
    """Insert and return a test store with slug ``test-store``.

    Args:
        db_session: The in-memory async database session.
        mock_store_id: A deterministic UUID for the store.

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
    """Return a list of sample ScrapedItem instances for testing.

    Returns:
        Three ScrapedItem objects with varied field combinations.
    """
    return [
        ScrapedItem(
            name="  мляко прясно  ",
            price=Decimal("2.49"),
            currency="EUR",
            unit="l",
            barcode="5901234123457",
            source="web",
            raw={"original": "milk"},
        ),
        ScrapedItem(
            name="хляб бял  ",
            price=Decimal("1.29"),
            currency="EUR",
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
    """Return a single normalised ScrapedItem for pipeline tests.

    Returns:
        A ScrapedItem ready to pass to ``process_scrape``.
    """
    return ScrapedItem(
        name="Мляко Прясно",
        price=Decimal("2.49"),
        currency="EUR",
        unit="l",
        barcode="5901234123457",
        source="web",
        raw={},
    )
