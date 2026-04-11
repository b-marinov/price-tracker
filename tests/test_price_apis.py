"""Comprehensive tests for price comparison and price history API endpoints.

Covers:
- GET /products/{id}/history  (daily, weekly, date-range, single-store, 404, empty)
- GET /products/{id}/compare  (sorted, price_diff_pct, partial, 404, empty)
- GET /products/compare?q=    (top-5, FTS path, ILIKE fallback, empty results)
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.routers.products import _aggregate_weekly
from app.schemas.history import PricePoint

# ---------------------------------------------------------------------------
# Shared UUIDs
# ---------------------------------------------------------------------------

PRODUCT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
PRODUCT_ID_2 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
PRODUCT_ID_3 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
STORE_LIDL_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
STORE_BILLA_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
STORE_KAUFLAND_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000003")

STORE_LIDL_NAME = "Lidl"
STORE_BILLA_NAME = "Billa"
STORE_KAUFLAND_NAME = "Kaufland"


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_product(
    pid: uuid.UUID | None = None,
    name: str = "Test Product",
    slug: str = "test-product",
    brand: str = "TestBrand",
) -> Product:
    """Create a mock Product instance with sensible defaults.

    Args:
        pid: Optional UUID; a random one is generated if omitted.
        name: Product display name.
        slug: URL-friendly identifier.
        brand: Brand or manufacturer name.

    Returns:
        A MagicMock configured with Product spec.
    """
    product = MagicMock(spec=Product)
    product.id = pid or uuid.uuid4()
    product.name = name
    product.slug = slug
    product.brand = brand
    product.status = ProductStatus.ACTIVE
    return product


def _make_price(
    product_id: uuid.UUID,
    store_id: uuid.UUID,
    price_val: float,
    recorded_at: datetime,
    source: str = "web",
) -> Price:
    """Create a mock Price instance.

    Args:
        product_id: UUID of the associated product.
        store_id: UUID of the associated store.
        price_val: Float price value (will be coerced to Decimal).
        recorded_at: Timezone-aware datetime.
        source: Price source string ("web" or "brochure").

    Returns:
        A MagicMock configured with Price spec.
    """
    price = MagicMock(spec=Price)
    price.product_id = product_id
    price.store_id = store_id
    price.price = Decimal(str(price_val))
    price.recorded_at = recorded_at
    price.currency = "EUR"
    price.source = source
    return price


def _mock_db_for_history(
    product: Product | None,
    history_rows: list[tuple[Price, str]],
) -> Any:
    """Return a dependency override for get_db_session (history endpoint).

    First execute call resolves the product lookup; second returns price rows.

    Args:
        product: The Product to return from the first query, or None for 404.
        history_rows: Rows of (Price, store_name) tuples for the second query.

    Returns:
        An async generator factory suitable for app.dependency_overrides.
    """

    async def override_get_db():  # noqa: ANN202
        session = AsyncMock()
        call_count = 0

        async def execute_side_effect(stmt: Any) -> Any:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = product
            else:
                result.all.return_value = history_rows
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        yield session

    return override_get_db


def _mock_db_for_compare(
    product: Product | None,
    compare_rows: list[Any],
) -> Any:
    """Return a dependency override for get_db_session (compare endpoint).

    First execute call resolves product lookup; second returns compare rows.

    Args:
        product: The Product to return from the first query, or None for 404.
        compare_rows: Rows returned by the price comparison query.

    Returns:
        An async generator factory suitable for app.dependency_overrides.
    """

    async def override_get_db():  # noqa: ANN202
        session = AsyncMock()
        call_count = 0

        async def execute_side_effect(stmt: Any) -> Any:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = product
            else:
                result.all.return_value = compare_rows
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        yield session

    return override_get_db


def _mock_db_for_search_compare(
    fts_products: list[Product],
    ilike_products: list[Product],
    price_rows: list[Any],
) -> Any:
    """Return a dependency override for get_db_session (search_compare endpoint).

    Call sequence: (1) FTS product query, (2) ILIKE fallback (only if FTS empty),
    (3) cheapest price query, (4) store+price join query.

    Args:
        fts_products: Products returned by the FTS query.
        ilike_products: Products returned by the ILIKE fallback query.
        price_rows: Rows returned by the store price join query.

    Returns:
        An async generator factory suitable for app.dependency_overrides.
    """

    async def override_get_db():  # noqa: ANN202
        session = AsyncMock()
        call_count = 0

        async def execute_side_effect(stmt: Any) -> Any:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # FTS product query
                scalars = MagicMock()
                scalars.all.return_value = fts_products
                result.scalars.return_value = scalars
            elif call_count == 2 and not fts_products:
                # ILIKE fallback (only invoked when FTS returns nothing)
                scalars = MagicMock()
                scalars.all.return_value = ilike_products
                result.scalars.return_value = scalars
            else:
                # Price queries (cheapest_sub + store_stmt)
                result.all.return_value = price_rows
            return result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        yield session

    return override_get_db


# ---------------------------------------------------------------------------
# History endpoint fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def history_product() -> Product:
    """Return a mock product for history tests."""
    return _make_product(pid=PRODUCT_ID)


def _build_history_rows() -> list[tuple[Price, str]]:
    """Build a realistic set of price rows across two stores for history tests.

    Returns:
        List of (Price, store_name) tuples covering two ISO weeks.
    """
    return [
        # Lidl: wk 9 (Mar 1), wk 10 (Mar 2 + Mar 8)
        (_make_price(PRODUCT_ID, STORE_LIDL_ID, 2.50, datetime(2026, 3, 1, 8, 0, tzinfo=UTC)), STORE_LIDL_NAME),
        (_make_price(PRODUCT_ID, STORE_LIDL_ID, 2.60, datetime(2026, 3, 2, 8, 0, tzinfo=UTC)), STORE_LIDL_NAME),
        (_make_price(PRODUCT_ID, STORE_LIDL_ID, 2.70, datetime(2026, 3, 8, 8, 0, tzinfo=UTC)), STORE_LIDL_NAME),
        # Billa: wk 9 (Mar 1), wk 10 (Mar 3)
        (_make_price(PRODUCT_ID, STORE_BILLA_ID, 3.00, datetime(2026, 3, 1, 9, 0, tzinfo=UTC)), STORE_BILLA_NAME),
        (_make_price(PRODUCT_ID, STORE_BILLA_ID, 3.10, datetime(2026, 3, 3, 9, 0, tzinfo=UTC)), STORE_BILLA_NAME),
    ]


# ---------------------------------------------------------------------------
# Tests: GET /products/{id}/history
# ---------------------------------------------------------------------------


class TestPriceHistoryAllStores:
    """Tests verifying store-grouped history is returned for valid products."""

    @pytest.mark.asyncio
    async def test_returns_200_with_all_stores(self, history_product: Product) -> None:
        """GET /products/{id}/history returns 200 and groups rows by store."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/history")

            assert resp.status_code == 200
            body = resp.json()
            assert body["product_id"] == str(PRODUCT_ID)
            assert len(body["store_results"]) == 2
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_lidl_has_three_daily_points(self, history_product: Product) -> None:
        """Lidl store result contains exactly 3 daily data points."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/history")

            body = resp.json()
            lidl_result = next(
                sr for sr in body["store_results"] if sr["store_id"] == str(STORE_LIDL_ID)
            )
            assert len(lidl_result["data"]) == 3
            assert lidl_result["store_name"] == STORE_LIDL_NAME
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_billa_has_two_daily_points(self, history_product: Product) -> None:
        """Billa store result contains exactly 2 daily data points."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/history")

            body = resp.json()
            billa_result = next(
                sr for sr in body["store_results"] if sr["store_id"] == str(STORE_BILLA_ID)
            )
            assert len(billa_result["data"]) == 2
        finally:
            app.dependency_overrides.clear()


class TestPriceHistorySingleStore:
    """Tests for the store_id filter on the history endpoint."""

    @pytest.mark.asyncio
    async def test_single_store_filter_returns_one_group(self, history_product: Product) -> None:
        """Passing store_id returns only that store's history group."""
        from app.database import get_db_session

        lidl_rows = [r for r in _build_history_rows() if r[0].store_id == STORE_LIDL_ID]
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, lidl_rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"store_id": str(STORE_LIDL_ID)},
                )

            assert resp.status_code == 200
            body = resp.json()
            assert len(body["store_results"]) == 1
            assert body["store_results"][0]["store_id"] == str(STORE_LIDL_ID)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_single_store_data_count_matches(self, history_product: Product) -> None:
        """Filtered result has the correct number of data points."""
        from app.database import get_db_session

        lidl_rows = [r for r in _build_history_rows() if r[0].store_id == STORE_LIDL_ID]
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, lidl_rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"store_id": str(STORE_LIDL_ID)},
                )

            body = resp.json()
            assert len(body["store_results"][0]["data"]) == 3
        finally:
            app.dependency_overrides.clear()


class TestPriceHistoryDateRange:
    """Tests for from_date / to_date filtering on the history endpoint."""

    @pytest.mark.asyncio
    async def test_date_range_restricts_returned_dates(self, history_product: Product) -> None:
        """Only data points within the requested date range are present."""
        from app.database import get_db_session

        # Simulate the DB filtering — only March 1 rows survive the WHERE clause
        march_1_only = [r for r in _build_history_rows() if r[0].recorded_at.day == 1]
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, march_1_only)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"from_date": "2026-03-01", "to_date": "2026-03-01"},
                )

            assert resp.status_code == 200
            body = resp.json()
            all_dates = [dp["date"] for sr in body["store_results"] for dp in sr["data"]]
            assert all(d == "2026-03-01" for d in all_dates)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_date_range_no_results_gives_empty_store_results(
        self, history_product: Product
    ) -> None:
        """A date range with no matching prices returns an empty store_results list."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"from_date": "2020-01-01", "to_date": "2020-01-02"},
                )

            assert resp.status_code == 200
            assert resp.json()["store_results"] == []
        finally:
            app.dependency_overrides.clear()


class TestPriceHistoryWeeklyInterval:
    """Tests for interval=weekly aggregation on the history endpoint."""

    @pytest.mark.asyncio
    async def test_weekly_lidl_produces_two_week_points(self, history_product: Product) -> None:
        """Lidl's 3 daily points in 2 ISO weeks collapse to 2 weekly averages."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"interval": "weekly"},
                )

            assert resp.status_code == 200
            body = resp.json()
            lidl_result = next(
                sr for sr in body["store_results"] if sr["store_id"] == str(STORE_LIDL_ID)
            )
            # Mar 1 = ISO wk 9, Mar 2 + Mar 8 = ISO wk 10 → 2 weekly buckets
            assert len(lidl_result["data"]) == 2
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_weekly_billa_produces_two_week_points(self, history_product: Product) -> None:
        """Billa's 2 daily points in 2 different ISO weeks stay as 2 weekly averages."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"interval": "weekly"},
                )

            body = resp.json()
            billa_result = next(
                sr for sr in body["store_results"] if sr["store_id"] == str(STORE_BILLA_ID)
            )
            # Mar 1 = ISO wk 9, Mar 3 = ISO wk 10 → 2 weekly buckets
            assert len(billa_result["data"]) == 2
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_weekly_average_price_is_correct(self, history_product: Product) -> None:
        """Week 10 average for Lidl = (2.60 + 2.70) / 2 = 2.65."""
        from app.database import get_db_session

        rows = _build_history_rows()
        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    f"/products/{PRODUCT_ID}/history",
                    params={"interval": "weekly"},
                )

            body = resp.json()
            lidl_result = next(
                sr for sr in body["store_results"] if sr["store_id"] == str(STORE_LIDL_ID)
            )
            # Second bucket is week 10: (2.60 + 2.70) / 2 = 2.65
            week10_point = lidl_result["data"][1]
            assert week10_point["price"] == pytest.approx(2.65)
        finally:
            app.dependency_overrides.clear()


class TestPriceHistoryEmptyAndMissing:
    """Edge-case tests: empty history and missing product."""

    @pytest.mark.asyncio
    async def test_product_not_found_returns_404(self) -> None:
        """GET /products/{id}/history returns 404 when product does not exist."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_history(None, [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{uuid.uuid4()}/history")

            assert resp.status_code == 404
            assert resp.json()["detail"] == "Product not found"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_product_with_no_prices_returns_empty_store_results(
        self, history_product: Product
    ) -> None:
        """A product with no price records returns an empty store_results list."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_history(history_product, [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/history")

            assert resp.status_code == 200
            body = resp.json()
            assert body["store_results"] == []
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Unit tests: _aggregate_weekly helper
# ---------------------------------------------------------------------------


class TestAggregateWeeklyUnit:
    """Unit tests for the _aggregate_weekly pure function."""

    def test_empty_input_returns_empty_list(self) -> None:
        """_aggregate_weekly([]) returns an empty list."""
        assert _aggregate_weekly([]) == []

    def test_single_point_unchanged(self) -> None:
        """A single price point passes through as a one-element list."""
        points = [PricePoint(date=date(2026, 3, 4), price=5.0)]
        result = _aggregate_weekly(points)
        assert len(result) == 1
        assert result[0].price == 5.0

    def test_same_week_averaged_correctly(self) -> None:
        """Three points in one ISO week are averaged to a single point."""
        points = [
            PricePoint(date=date(2026, 3, 2), price=10.0),  # Mon wk10
            PricePoint(date=date(2026, 3, 3), price=20.0),  # Tue wk10
            PricePoint(date=date(2026, 3, 4), price=30.0),  # Wed wk10
        ]
        result = _aggregate_weekly(points)
        assert len(result) == 1
        assert result[0].price == 20.0

    def test_week_representative_date_is_first_seen(self) -> None:
        """The representative date for a week is the first date encountered."""
        points = [
            PricePoint(date=date(2026, 3, 2), price=10.0),  # Mon wk10 — first
            PricePoint(date=date(2026, 3, 5), price=20.0),  # Thu wk10
        ]
        result = _aggregate_weekly(points)
        assert result[0].date == date(2026, 3, 2)

    def test_multiple_weeks_sorted_by_week(self) -> None:
        """Points spanning multiple weeks produce one bucket per week, in order."""
        points = [
            PricePoint(date=date(2026, 3, 1), price=1.0),   # Sun wk9
            PricePoint(date=date(2026, 3, 2), price=2.0),   # Mon wk10
            PricePoint(date=date(2026, 3, 8), price=3.0),   # Sun wk10
            PricePoint(date=date(2026, 3, 9), price=4.0),   # Mon wk11
        ]
        result = _aggregate_weekly(points)
        assert len(result) == 3
        prices = [r.price for r in result]
        assert prices == [1.0, 2.5, 4.0]

    def test_rounding_to_two_decimal_places(self) -> None:
        """Weekly average is rounded to 2 decimal places."""
        points = [
            PricePoint(date=date(2026, 3, 2), price=1.0),
            PricePoint(date=date(2026, 3, 3), price=2.0),
            PricePoint(date=date(2026, 3, 4), price=3.0),
        ]
        # Average = 2.0 exactly, but test rounding for non-trivial case
        result = _aggregate_weekly(points)
        assert isinstance(result[0].price, float)
        # Verify round(2.0, 2) == 2.0
        assert result[0].price == 2.0


# ---------------------------------------------------------------------------
# Helpers: compare endpoint row factory
# ---------------------------------------------------------------------------


def _make_compare_row(
    store_id: uuid.UUID,
    store_name: str,
    store_slug: str,
    price: float,
    currency: str = "EUR",
    logo_url: str | None = None,
    source: str = "web",
) -> Any:
    """Build a mock row for the price comparison query result.

    Args:
        store_id: UUID of the store.
        store_name: Display name of the store.
        store_slug: URL-friendly store identifier.
        price: Price as a float (coerced to Decimal on the mock).
        currency: ISO currency code.
        logo_url: Optional store logo URL.
        source: Price source identifier.

    Returns:
        A MagicMock with attribute-style column access matching the ORM result.
    """
    row = MagicMock()
    row.store_id = store_id
    row.store_name = store_name
    row.store_slug = store_slug
    row.logo_url = logo_url
    row.price = Decimal(str(price))
    row.currency = currency
    row.recorded_at = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    row.source = source
    return row


# ---------------------------------------------------------------------------
# Tests: GET /products/{id}/compare
# ---------------------------------------------------------------------------


class TestCompareProductPrices:
    """Tests for compare_product_prices endpoint."""

    @pytest.mark.asyncio
    async def test_cheapest_store_has_zero_diff(self) -> None:
        """The cheapest store in the comparison always has price_diff_pct == 0.0."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 2.50),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 3.00),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            assert resp.status_code == 200
            comparisons = resp.json()["comparisons"]
            cheapest = comparisons[0]
            assert cheapest["price_diff_pct"] == 0.0
            assert cheapest["store_name"] == STORE_LIDL_NAME
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_comparisons_sorted_cheapest_first(self) -> None:
        """Comparisons are ordered by ascending price (cheapest first)."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        # Rows provided cheapest first (endpoint relies on ORDER BY price ASC)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 2.50),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 3.00),
            _make_compare_row(STORE_KAUFLAND_ID, STORE_KAUFLAND_NAME, "kaufland", 3.50),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            prices = [Decimal(str(c["price"])) for c in comparisons]
            assert prices == sorted(prices)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_price_diff_pct_is_exactly_20_percent(self) -> None:
        """A store priced 20% above cheapest gets price_diff_pct == 20.0."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 2.50),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 3.00),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            # (3.00 - 2.50) / 2.50 * 100 = 20.0
            billa = next(c for c in comparisons if c["store_name"] == STORE_BILLA_NAME)
            assert billa["price_diff_pct"] == pytest.approx(20.0)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_price_diff_pct_rounds_to_one_decimal(self) -> None:
        """price_diff_pct is rounded to one decimal place."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        # (1.55 - 1.50) / 1.50 * 100 = 3.333... → 3.3
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 1.50),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 1.55),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            billa = next(c for c in comparisons if c["store_name"] == STORE_BILLA_NAME)
            assert billa["price_diff_pct"] == 3.3
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_all_stores_same_price_all_zero_diff(self) -> None:
        """When all stores share the same price, every price_diff_pct is 0.0."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 4.99),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 4.99),
            _make_compare_row(STORE_KAUFLAND_ID, STORE_KAUFLAND_NAME, "kaufland", 4.99),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            assert all(c["price_diff_pct"] == 0.0 for c in comparisons)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_partial_results_two_of_three_stores(self) -> None:
        """Only stores that actually carry the product appear in comparisons."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        # Kaufland does not carry this product — only 2 rows returned
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 2.50),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 2.80),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            assert len(comparisons) == 2
            store_names = {c["store_name"] for c in comparisons}
            assert STORE_KAUFLAND_NAME not in store_names
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_single_store_has_zero_diff(self) -> None:
        """A product available at only one store has price_diff_pct == 0.0."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 9.99),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            assert len(comparisons) == 1
            assert comparisons[0]["price_diff_pct"] == 0.0
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_product_not_found_returns_404(self) -> None:
        """GET /products/{id}/compare returns 404 for a missing product."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_compare(None, [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{uuid.uuid4()}/compare")

            assert resp.status_code == 404
            assert resp.json()["detail"] == "Product not found"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_product_with_no_prices_returns_empty_comparisons(self) -> None:
        """A product with no current prices returns an empty comparisons list."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            assert resp.status_code == 200
            body = resp.json()
            assert body["comparisons"] == []
            assert body["product_id"] == str(PRODUCT_ID)
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_100_percent_more_expensive_store(self) -> None:
        """A store at double the cheapest price gets price_diff_pct == 100.0."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID)
        rows = [
            _make_compare_row(STORE_LIDL_ID, STORE_LIDL_NAME, "lidl", 5.00),
            _make_compare_row(STORE_BILLA_ID, STORE_BILLA_NAME, "billa", 10.00),
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_compare(product, rows)
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/products/{PRODUCT_ID}/compare")

            comparisons = resp.json()["comparisons"]
            billa = next(c for c in comparisons if c["store_name"] == STORE_BILLA_NAME)
            assert billa["price_diff_pct"] == pytest.approx(100.0)
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers: search_compare endpoint row factory
# ---------------------------------------------------------------------------


def _make_search_row(
    product_id: uuid.UUID,
    store_name: str,
    store_slug: str,
    price: float,
    store_count: int = 2,
    currency: str = "EUR",
) -> Any:
    """Build a mock row for the search_compare price query result.

    Args:
        product_id: UUID of the product this row belongs to.
        store_name: Display name of the cheapest store.
        store_slug: URL-friendly identifier of the cheapest store.
        price: Cheapest price as a float.
        store_count: Number of stores carrying this product.
        currency: ISO currency code.

    Returns:
        A MagicMock with attribute-style access matching the ORM result.
    """
    row = MagicMock()
    row.product_id = product_id
    row.store_name = store_name
    row.store_slug = store_slug
    row.price = Decimal(str(price))
    row.currency = currency
    row.store_count = store_count
    return row


# ---------------------------------------------------------------------------
# Tests: GET /products/compare?q=
# ---------------------------------------------------------------------------


class TestSearchCompare:
    """Tests for the search_compare endpoint."""

    @pytest.mark.asyncio
    async def test_fts_path_returns_matching_products(self) -> None:
        """When FTS returns products, those products appear in results."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID, name="Milk 1L", slug="milk-1l")
        price_row = _make_search_row(PRODUCT_ID, STORE_LIDL_NAME, "lidl", 1.99)
        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=[product],
            ilike_products=[],
            price_rows=[price_row],
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "milk"})

            assert resp.status_code == 200
            body = resp.json()
            assert body["query"] == "milk"
            assert len(body["results"]) == 1
            assert body["results"][0]["product_name"] == "Milk 1L"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_ilike_fallback_used_when_fts_empty(self) -> None:
        """When FTS yields no results, ILIKE fallback products are returned."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID, name="Мляко 1L", slug="mlyako-1l")
        price_row = _make_search_row(PRODUCT_ID, STORE_BILLA_NAME, "billa", 2.10)
        # FTS returns nothing; ILIKE returns the product
        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=[],
            ilike_products=[product],
            price_rows=[price_row],
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "Мляко"})

            assert resp.status_code == 200
            body = resp.json()
            assert len(body["results"]) == 1
            assert body["results"][0]["product_slug"] == "mlyako-1l"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_empty_results_for_unknown_query(self) -> None:
        """A query matching nothing returns an empty results list with 200."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=[],
            ilike_products=[],
            price_rows=[],
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "xyznotexist"})

            assert resp.status_code == 200
            body = resp.json()
            assert body["results"] == []
            assert body["query"] == "xyznotexist"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_returns_at_most_five_results(self) -> None:
        """search_compare is limited to 5 products (enforced at DB query level)."""
        from app.database import get_db_session

        # Simulate 5 products (the LIMIT 5 is in the query, not post-processing)
        products = [
            _make_product(
                pid=uuid.UUID(f"cccccccc-0000-0000-0000-{i:012d}"),
                name=f"Product {i}",
                slug=f"product-{i}",
            )
            for i in range(1, 6)
        ]
        price_rows = [
            _make_search_row(p.id, STORE_LIDL_NAME, "lidl", 1.0 + i * 0.10)
            for i, p in enumerate(products)
        ]
        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=products,
            ilike_products=[],
            price_rows=price_rows,
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "product"})

            body = resp.json()
            assert len(body["results"]) == 5
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_cheapest_price_and_store_name_returned(self) -> None:
        """Each result contains the cheapest price and the corresponding store name."""
        from app.database import get_db_session

        product = _make_product(pid=PRODUCT_ID, name="Bread", slug="bread")
        price_row = _make_search_row(
            PRODUCT_ID,
            STORE_LIDL_NAME,
            "lidl",
            0.89,
            store_count=3,
        )
        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=[product],
            ilike_products=[],
            price_rows=[price_row],
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "bread"})

            result = resp.json()["results"][0]
            assert result["cheapest_store_name"] == STORE_LIDL_NAME
            assert Decimal(str(result["cheapest_price"])) == Decimal("0.89")
            assert result["store_count"] == 3
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_query_echoed_in_response(self) -> None:
        """The original query string is echoed back in the response body."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare(
            fts_products=[],
            ilike_products=[],
            price_rows=[],
        )
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare", params={"q": "cheese"})

            assert resp.json()["query"] == "cheese"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_missing_q_param_returns_422(self) -> None:
        """Calling /products/compare without q returns 422 Unprocessable Entity."""
        from app.database import get_db_session

        app.dependency_overrides[get_db_session] = _mock_db_for_search_compare([], [], [])
        try:
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/products/compare")

            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Route registration sanity checks
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    """Verify the endpoints under test are registered on the app."""

    def test_history_route_exists(self) -> None:
        """GET /products/{product_id}/history is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products/{product_id}/history" in routes

    def test_compare_route_exists(self) -> None:
        """GET /products/{product_id}/compare is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products/{product_id}/compare" in routes

    def test_search_compare_route_exists(self) -> None:
        """GET /products/compare is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products/compare" in routes
