"""Tests for the price history API endpoint."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.price import Price, PriceSource
from app.models.product import Product
from app.routers.products import _aggregate_weekly
from app.schemas.history import PricePoint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(pid: uuid.UUID | None = None) -> Product:
    """Create a mock Product instance."""
    product = MagicMock(spec=Product)
    product.id = pid or uuid.uuid4()
    product.name = "Test Product"
    product.slug = "test-product"
    product.brand = "TestBrand"
    return product


def _make_price(
    product_id: uuid.UUID,
    store_id: uuid.UUID,
    price_val: float,
    recorded_at: datetime,
) -> Price:
    """Create a mock Price instance."""
    price = MagicMock(spec=Price)
    price.product_id = product_id
    price.store_id = store_id
    price.price = Decimal(str(price_val))
    price.recorded_at = recorded_at
    price.currency = "EUR"
    price.source = PriceSource.WEB
    return price


PRODUCT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
STORE_A_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
STORE_B_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")
STORE_A_NAME = "Store Alpha"
STORE_B_NAME = "Store Beta"


def _build_rows() -> list[tuple[Price, str]]:
    """Build mock DB rows with prices across two stores."""
    return [
        (_make_price(PRODUCT_ID, STORE_A_ID, 1.50, datetime(2026, 3, 1, 10, 0, tzinfo=UTC)), STORE_A_NAME),
        (_make_price(PRODUCT_ID, STORE_A_ID, 1.60, datetime(2026, 3, 2, 10, 0, tzinfo=UTC)), STORE_A_NAME),
        (_make_price(PRODUCT_ID, STORE_A_ID, 1.70, datetime(2026, 3, 8, 10, 0, tzinfo=UTC)), STORE_A_NAME),
        (_make_price(PRODUCT_ID, STORE_B_ID, 2.00, datetime(2026, 3, 1, 12, 0, tzinfo=UTC)), STORE_B_NAME),
        (_make_price(PRODUCT_ID, STORE_B_ID, 2.10, datetime(2026, 3, 3, 12, 0, tzinfo=UTC)), STORE_B_NAME),
    ]


# ---------------------------------------------------------------------------
# Mock database dependency
# ---------------------------------------------------------------------------

def _mock_db_session(product: Product | None, rows: list[tuple[Price, str]]):
    """Return a patched get_db_session that yields a mock AsyncSession.

    The mock session handles two query patterns:
    1. select(Product) -> returns the product (or None for 404)
    2. select(Price, Store.name) -> returns the price rows
    """

    async def override_get_db():
        session = AsyncMock()
        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Product lookup
                result.scalar_one_or_none.return_value = product
            else:
                # Price query
                result.all.return_value = rows
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        yield session

    return override_get_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def product() -> Product:
    """Return a mock product."""
    return _make_product(PRODUCT_ID)


@pytest.fixture
def all_rows() -> list[tuple[Price, str]]:
    """Return all mock price rows."""
    return _build_rows()


@pytest.mark.asyncio
async def test_price_history_all_stores(product: Product, all_rows: list) -> None:
    """GET /products/{id}/history returns data grouped by all stores."""
    from app.database import get_db_session

    app.dependency_overrides[get_db_session] = _mock_db_session(product, all_rows)
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/products/{PRODUCT_ID}/history")

        assert resp.status_code == 200
        body = resp.json()
        assert body["product_id"] == str(PRODUCT_ID)
        assert len(body["store_results"]) == 2

        store_ids = {sr["store_id"] for sr in body["store_results"]}
        assert str(STORE_A_ID) in store_ids
        assert str(STORE_B_ID) in store_ids

        # Store A has 3 data points, Store B has 2
        for sr in body["store_results"]:
            if sr["store_id"] == str(STORE_A_ID):
                assert len(sr["data"]) == 3
                assert sr["store_name"] == STORE_A_NAME
            else:
                assert len(sr["data"]) == 2
                assert sr["store_name"] == STORE_B_NAME
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_price_history_single_store(product: Product) -> None:
    """GET /products/{id}/history?store_id=X filters to one store."""
    from app.database import get_db_session

    # Only Store A rows
    rows = [r for r in _build_rows() if r[0].store_id == STORE_A_ID]
    app.dependency_overrides[get_db_session] = _mock_db_session(product, rows)
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/products/{PRODUCT_ID}/history",
                params={"store_id": str(STORE_A_ID)},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["store_results"]) == 1
        assert body["store_results"][0]["store_id"] == str(STORE_A_ID)
        assert len(body["store_results"][0]["data"]) == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_price_history_date_range(product: Product) -> None:
    """GET /products/{id}/history with from_date and to_date filters results."""
    from app.database import get_db_session

    # Simulate filtered rows (only March 1-2)
    filtered = [r for r in _build_rows() if r[0].recorded_at.day <= 2]
    app.dependency_overrides[get_db_session] = _mock_db_session(product, filtered)
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/products/{PRODUCT_ID}/history",
                params={"from_date": "2026-03-01", "to_date": "2026-03-02"},
            )

        assert resp.status_code == 200
        body = resp.json()
        # Should only have points from March 1-2
        all_dates = []
        for sr in body["store_results"]:
            for dp in sr["data"]:
                all_dates.append(dp["date"])
        assert all(d in ("2026-03-01", "2026-03-02") for d in all_dates)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_price_history_weekly_aggregation(product: Product, all_rows: list) -> None:
    """GET /products/{id}/history?interval=weekly aggregates by ISO week."""
    from app.database import get_db_session

    app.dependency_overrides[get_db_session] = _mock_db_session(product, all_rows)
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/products/{PRODUCT_ID}/history",
                params={"interval": "weekly"},
            )

        assert resp.status_code == 200
        body = resp.json()

        for sr in body["store_results"]:
            if sr["store_id"] == str(STORE_A_ID):
                # March 1 (Sun, wk 9) and March 2 (Mon, wk 10) are different weeks;
                # March 8 (Sun, wk 10) is same week as March 2.
                # So Store A should have 2 weekly points
                assert len(sr["data"]) == 2
            else:
                # Store B: March 1 (wk 9) and March 3 (wk 10) -> 2 weekly points
                assert len(sr["data"]) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_price_history_product_not_found() -> None:
    """GET /products/{id}/history returns 404 for non-existent product."""
    from app.database import get_db_session

    missing_id = uuid.uuid4()
    app.dependency_overrides[get_db_session] = _mock_db_session(None, [])
    try:
        transport = ASGITransport(app=app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/products/{missing_id}/history")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Product not found"
    finally:
        app.dependency_overrides.clear()


def test_aggregate_weekly_empty() -> None:
    """_aggregate_weekly returns empty list for empty input."""
    assert _aggregate_weekly([]) == []


def test_aggregate_weekly_computes_average() -> None:
    """_aggregate_weekly correctly averages prices within the same ISO week."""
    points = [
        PricePoint(date=date(2026, 3, 2), price=10.0),  # Monday wk 10
        PricePoint(date=date(2026, 3, 3), price=20.0),  # Tuesday wk 10
        PricePoint(date=date(2026, 3, 4), price=30.0),  # Wednesday wk 10
    ]
    result = _aggregate_weekly(points)
    assert len(result) == 1
    assert result[0].date == date(2026, 3, 2)
    assert result[0].price == 20.0
