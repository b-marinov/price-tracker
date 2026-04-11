"""Integration tests for the browse API endpoints (app/routers/browse.py).

Covers:
- GET /browse   — returns category hierarchy (BrowseResponse)
- GET /browse/deals   — returns items sorted by discount_percent DESC

The database session is overridden via FastAPI dependency injection so no
real PostgreSQL connection is needed.  Each test builds a minimal mock
session that returns the exact rows required by the endpoint's SQL queries.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db_session
from app.main import app

# ---------------------------------------------------------------------------
# Shared async client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    """Provide an async HTTP test client bound to the FastAPI app.

    Yields:
        AsyncClient: A ready-to-use httpx async client.
    """
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_browse_row(
    top_category: str = "Dairy",
    category: str = "Milk",
    product_type: str | None = "Whole",
    brand: str | None = "Meggle",
    price_min: float = 1.20,
    price_max: float = 1.80,
    max_discount: int | None = None,
    store_count: int = 2,
    cheapest_store: str | None = "Lidl",
) -> MagicMock:
    """Build a MagicMock result row for the /browse aggregation query.

    Args:
        top_category: Top-level category label.
        category: Sub-category label.
        product_type: Product type label or None.
        brand: Brand name or None (None triggers 'Собствена марка' label).
        price_min: Minimum observed price.
        price_max: Maximum observed price.
        max_discount: Largest discount percentage, or None.
        store_count: Number of distinct stores.
        cheapest_store: Name of the store with the lowest price.

    Returns:
        MagicMock with named column attributes matching the SQLAlchemy row.
    """
    row = MagicMock()
    row.top_category = top_category
    row.category = category
    row.product_type = product_type
    row.brand = brand
    row.price_min = price_min
    row.price_max = price_max
    row.max_discount = max_discount
    row.store_count = store_count
    row.cheapest_store = cheapest_store
    return row


def _make_deal_row(
    product_name: str = "Soap",
    brand: str | None = "Dove",
    store_name: str = "Lidl",
    price: float = 0.99,
    original_price: float | None = 1.49,
    discount_percent: int = 33,
    top_category: str | None = "Hygiene",
    category: str | None = "Body Care",
    image_url: str | None = None,
) -> MagicMock:
    """Build a MagicMock result row for the /browse/deals data query.

    Args:
        product_name: Display name of the product.
        brand: Brand name or None.
        store_name: Name of the store carrying this deal.
        price: Discounted price.
        original_price: Pre-discount price, or None.
        discount_percent: Discount percentage (must be > 0).
        top_category: Top-level category, or None.
        category: Sub-category, or None.
        image_url: Image URL, or None.

    Returns:
        MagicMock with named column attributes.
    """
    row = MagicMock()
    row.product_name = product_name
    row.brand = brand
    row.store_name = store_name
    row.price = Decimal(str(price))
    row.original_price = Decimal(str(original_price)) if original_price is not None else None
    row.discount_percent = discount_percent
    row.top_category = top_category
    row.category = category
    row.image_url = image_url
    return row


# ---------------------------------------------------------------------------
# GET /browse
# ---------------------------------------------------------------------------


class TestBrowse:
    """GET /browse returns a structured category hierarchy."""

    async def test_returns_200(self, client: AsyncClient) -> None:
        """A successful call to /browse returns HTTP 200."""
        mock_db = AsyncMock()

        agg_result = MagicMock()
        agg_result.all.return_value = []

        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200

    async def test_empty_db_returns_empty_top_categories(
        self, client: AsyncClient
    ) -> None:
        """When no prices exist the hierarchy is empty."""
        mock_db = AsyncMock()

        agg_result = MagicMock()
        agg_result.all.return_value = []

        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        data = response.json()
        assert data["top_categories"] == []

    async def test_single_row_builds_correct_hierarchy(
        self, client: AsyncClient
    ) -> None:
        """A single aggregation row produces a complete four-level hierarchy."""
        row = _make_browse_row(
            top_category="Dairy",
            category="Milk",
            product_type="Whole",
            brand="Meggle",
            price_min=1.20,
            price_max=1.80,
        )

        mock_db = AsyncMock()

        agg_result = MagicMock()
        agg_result.all.return_value = [row]

        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        data = response.json()
        assert len(data["top_categories"]) == 1
        top = data["top_categories"][0]
        assert top["top_category"] == "Dairy"
        assert len(top["sub_categories"]) == 1
        sub = top["sub_categories"][0]
        assert sub["category"] == "Milk"
        assert len(sub["product_types"]) == 1
        pt = sub["product_types"][0]
        assert pt["product_type"] == "Whole"
        assert len(pt["brands"]) == 1
        assert pt["brands"][0]["brand"] == "Meggle"

    async def test_null_product_type_uses_default_label(
        self, client: AsyncClient
    ) -> None:
        """A None product_type is displayed as the 'Общо' label."""
        row = _make_browse_row(product_type=None)

        mock_db = AsyncMock()
        agg_result = MagicMock()
        agg_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        pt_name = (
            response.json()["top_categories"][0]["sub_categories"][0]
            ["product_types"][0]["product_type"]
        )
        assert pt_name == "Общо"

    async def test_null_brand_uses_own_brand_label(
        self, client: AsyncClient
    ) -> None:
        """A None brand value is displayed as 'Собствена марка'."""
        row = _make_browse_row(brand=None)

        mock_db = AsyncMock()
        agg_result = MagicMock()
        agg_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        brand_name = (
            response.json()["top_categories"][0]["sub_categories"][0]
            ["product_types"][0]["brands"][0]["brand"]
        )
        assert brand_name == "Собствена марка"

    async def test_top_categories_are_sorted_alphabetically(
        self, client: AsyncClient
    ) -> None:
        """Top categories appear in alphabetical order."""
        rows = [
            _make_browse_row(top_category="Vegetables", category="Tomatoes"),
            _make_browse_row(top_category="Dairy", category="Cheese"),
            _make_browse_row(top_category="Bakery", category="Bread"),
        ]

        mock_db = AsyncMock()
        agg_result = MagicMock()
        agg_result.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        names = [t["top_category"] for t in response.json()["top_categories"]]
        assert names == sorted(names)

    async def test_price_aggregation_propagates_to_top_level(
        self, client: AsyncClient
    ) -> None:
        """price_min and price_max at each level reflect the brand values below."""
        row = _make_browse_row(
            price_min=0.50,
            price_max=3.00,
        )

        mock_db = AsyncMock()
        agg_result = MagicMock()
        agg_result.all.return_value = [row]
        mock_db.execute = AsyncMock(return_value=agg_result)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        top = response.json()["top_categories"][0]
        assert top["price_min"] == pytest.approx(0.50)
        assert top["price_max"] == pytest.approx(3.00)


# ---------------------------------------------------------------------------
# GET /browse/deals
# ---------------------------------------------------------------------------


class TestBrowseDeals:
    """GET /browse/deals returns discounted items sorted by discount DESC."""

    async def test_returns_200(self, client: AsyncClient) -> None:
        """A call to /browse/deals returns HTTP 200."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200

    async def test_empty_result_returns_items_and_total(
        self, client: AsyncClient
    ) -> None:
        """An empty deals set returns items=[] and total=0."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_deals_include_required_fields(
        self, client: AsyncClient
    ) -> None:
        """Each deal item exposes all required DealItem fields."""
        deal = _make_deal_row(
            product_name="Shampoo",
            brand="Pantene",
            store_name="Kaufland",
            price=1.99,
            original_price=2.99,
            discount_percent=33,
        )

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        data_result.all.return_value = [deal]

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        item = response.json()["items"][0]
        assert item["product_name"] == "Shampoo"
        assert item["brand"] == "Pantene"
        assert item["store"] == "Kaufland"
        assert item["discount_percent"] == 33
        assert float(item["price"]) == pytest.approx(1.99)
        assert float(item["original_price"]) == pytest.approx(2.99)

    async def test_deals_sorted_by_discount_desc(
        self, client: AsyncClient
    ) -> None:
        """The DB is asked to order by discount_percent DESC (ordering is in SQL).

        This test verifies that the response preserves the order returned by
        the database (the endpoint does not re-sort in Python).
        """
        # Return rows already in DESC discount order as the DB would
        rows = [
            _make_deal_row(product_name="A", discount_percent=50),
            _make_deal_row(product_name="B", discount_percent=30),
            _make_deal_row(product_name="C", discount_percent=10),
        ]

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 3

        data_result = MagicMock()
        data_result.all.return_value = rows

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        discounts = [i["discount_percent"] for i in response.json()["items"]]
        assert discounts == [50, 30, 10]

    async def test_total_reflects_all_matching_rows(
        self, client: AsyncClient
    ) -> None:
        """The total field reflects the count query result, not just visible items."""
        rows = [_make_deal_row()]

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 42  # larger than the 1 row returned

        data_result = MagicMock()
        data_result.all.return_value = rows

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.json()["total"] == 42

    async def test_top_category_filter_is_accepted(
        self, client: AsyncClient
    ) -> None:
        """The top_category query param is accepted and returns 200."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals?top_category=Dairy")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200

    async def test_limit_param_is_respected(
        self, client: AsyncClient
    ) -> None:
        """The limit query param is accepted; valid values return 200."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals?limit=10")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200

    async def test_limit_above_max_returns_422(
        self, client: AsyncClient
    ) -> None:
        """A limit value greater than 200 is rejected with HTTP 422."""
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()
        try:
            response = await client.get("/browse/deals?limit=9999")
        finally:
            app.dependency_overrides.pop(get_db_session, None)
        assert response.status_code == 422

    async def test_deal_with_null_original_price(
        self, client: AsyncClient
    ) -> None:
        """A deal row with no original_price serialises original_price as null."""
        deal = _make_deal_row(original_price=None, discount_percent=15)

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        data_result.all.return_value = [deal]

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/browse/deals")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.json()["items"][0]["original_price"] is None
