"""Integration tests for catalogue API endpoints (app/routers/catalogue.py).

Tests exercise:
- GET /products   — paginated product list
- GET /products/{id}   — product detail with per-store prices
- GET /products/{id}   — 404 for unknown product id
- GET /products/search?q=...   — matching products via ILIKE fallback

The DB is fully mocked via FastAPI dependency overrides so no real PostgreSQL
connection is required.  Each test class sets up its own override and tears it
down in a finaliser, keeping tests isolated.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db_session
from app.main import app
from app.models.product import Product, ProductStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    name: str = "Test Product",
    slug: str = "test-product",
    status: ProductStatus = ProductStatus.ACTIVE,
    brand: str | None = None,
    barcode: str | None = None,
    category_id: uuid.UUID | None = None,
    image_url: str | None = None,
    pack_info: str | None = None,
    pack_type: str | None = None,
    generic_pack: str | None = None,
    additional_info: str | None = None,
) -> MagicMock:
    """Return a MagicMock that mimics a Product ORM instance.

    Args:
        name: Product display name.
        slug: URL-friendly slug.
        status: ProductStatus enum value.
        brand: Brand name or None.
        barcode: Barcode string or None.
        category_id: FK category UUID or None.
        image_url: Image URL or None.
        pack_info: Pack info string or None.
        additional_info: Additional info string or None.

    Returns:
        A MagicMock with the same attributes as Product.
    """
    p = MagicMock(spec=Product)
    p.id = uuid.uuid4()
    p.name = name
    p.slug = slug
    p.status = status
    p.brand = brand
    p.barcode = barcode
    p.category_id = category_id
    p.image_url = image_url
    p.pack_info = pack_info
    p.pack_type = pack_type
    p.generic_pack = generic_pack
    p.additional_info = additional_info
    p.created_at = datetime.now(tz=UTC)
    p.updated_at = datetime.now(tz=UTC)
    return p


def _make_price_row(
    product_id: uuid.UUID,
    store_id: uuid.UUID | None = None,
    store_name: str = "Lidl",
    store_slug: str = "lidl",
    price: Decimal = Decimal("2.99"),
    currency: str = "EUR",
    recorded_at: datetime | None = None,
) -> MagicMock:
    """Return a MagicMock that mimics a SQLAlchemy result row for price queries.

    Args:
        product_id: The product UUID.
        store_id: The store UUID.
        store_name: Display name of the store.
        store_slug: URL slug of the store.
        price: The price value.
        currency: ISO 4217 currency code.
        recorded_at: Timestamp of observation.

    Returns:
        A MagicMock with named column attributes.
    """
    row = MagicMock()
    row.store_id = store_id or uuid.uuid4()
    row.store_name = store_name
    row.store_slug = store_slug
    row.price = price
    row.currency = currency
    row.recorded_at = recorded_at or datetime.now(tz=UTC)
    row.unit = None
    row.pack_info = None
    row.pack_type = None
    row.generic_pack = None
    row.brand = None
    return row


def _make_enrich_row(
    product_id: uuid.UUID,
    lowest_price: Decimal = Decimal("2.99"),
    store_count: int = 1,
    last_updated: datetime | None = None,
) -> MagicMock:
    """Return a MagicMock row for the price enrichment subquery result.

    Args:
        product_id: The product UUID to key this row on.
        lowest_price: Minimum price across stores.
        store_count: Number of distinct stores carrying this product.
        last_updated: Most recent price observation timestamp.

    Returns:
        A MagicMock with named column attributes.
    """
    row = MagicMock()
    row.product_id = product_id
    row.lowest_price = lowest_price
    row.store_count = store_count
    row.last_updated = last_updated or datetime.now(tz=UTC)
    return row


# ---------------------------------------------------------------------------
# Shared async client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client bound to the FastAPI app.

    Yields:
        AsyncClient: A ready-to-use httpx async client.
    """
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /products — paginated list
# ---------------------------------------------------------------------------


class TestListProducts:
    """GET /products returns a paginated product list."""

    async def test_returns_200_with_product_list(
        self, client: AsyncClient
    ) -> None:
        """A successful response has status 200 and items/total/limit/offset."""
        product = _make_product()
        enrich_row = _make_enrich_row(product.id)

        mock_db = AsyncMock()

        # Scalar count result
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        # Product list result
        product_result = MagicMock()
        product_result.scalars.return_value.all.return_value = [product]

        # Enrichment price query result
        enrich_result = MagicMock()
        enrich_result.all.return_value = [enrich_row]

        mock_db.execute = AsyncMock(
            side_effect=[count_result, product_result, enrich_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 1
        assert data["limit"] == 20
        assert data["offset"] == 0

    async def test_returns_empty_list_when_no_products(
        self, client: AsyncClient
    ) -> None:
        """An empty database returns items=[] and total=0."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        product_result = MagicMock()
        product_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[count_result, product_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_pagination_params_are_forwarded(
        self, client: AsyncClient
    ) -> None:
        """limit and offset query params are reflected in the response envelope."""
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 5

        product_result = MagicMock()
        product_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[count_result, product_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products?limit=5&offset=10")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 5
        assert data["offset"] == 10

    async def test_product_fields_are_present(
        self, client: AsyncClient
    ) -> None:
        """Each item exposes the ProductFamilyListItem shape (name, name_slug,
        and the brand/pack/store/variant aggregate counters)."""
        product_id = uuid.uuid4()
        store_id = uuid.uuid4()

        # _paginated_families_where executes three queries: distinct-name
        # count, paginated name list, then variant rows joined with prices.
        # Mock each in order.
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        names_result = MagicMock()
        names_result.all.return_value = [("Olive Oil",)]

        variant_row = MagicMock()
        variant_row.product_id = product_id
        variant_row.name = "Olive Oil"
        variant_row.brand = "Acme"
        variant_row.pack_info = "1 л"
        variant_row.category_id = None
        variant_row.product_image_url = None
        variant_row.price = Decimal("4.99")
        variant_row.store_id = store_id
        variant_row.price_image_url = None
        variant_row.recorded_at = datetime.now(tz=UTC)

        variants_result = MagicMock()
        variants_result.all.return_value = [variant_row]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[count_result, names_result, variants_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db
        try:
            response = await client.get("/products")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        item = response.json()["items"][0]
        assert item["name"] == "Olive Oil"
        assert item["name_slug"] == "olive-oil"
        assert item["brand_count"] == 1
        assert item["pack_count"] == 1
        assert item["store_count"] == 1
        assert item["variant_count"] == 1
        assert item["lowest_price"] == "4.99"


# ---------------------------------------------------------------------------
# GET /products/{id} — product detail
# ---------------------------------------------------------------------------


class TestGetProduct:
    """GET /products/{id} returns product detail or 404."""

    async def test_returns_product_detail_for_known_id(
        self, client: AsyncClient
    ) -> None:
        """A known product ID returns 200 with full detail including prices."""
        product = _make_product(name="Butter")
        price_row = _make_price_row(product_id=product.id)

        mock_db = AsyncMock()

        # Product lookup result
        product_lookup = MagicMock()
        product_lookup.scalar_one_or_none.return_value = product

        # Price summaries result
        price_result = MagicMock()
        price_result.all.return_value = [price_row]

        mock_db.execute = AsyncMock(
            side_effect=[product_lookup, price_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get(f"/products/{product.id}")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Butter"
        assert "prices" in data
        assert len(data["prices"]) == 1

    async def test_returns_404_for_unknown_id(
        self, client: AsyncClient
    ) -> None:
        """An unknown product UUID returns HTTP 404."""
        mock_db = AsyncMock()

        product_lookup = MagicMock()
        product_lookup.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=product_lookup)

        app.dependency_overrides[get_db_session] = lambda: mock_db

        unknown_id = uuid.uuid4()
        try:
            response = await client.get(f"/products/{unknown_id}")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 404
        assert response.json()["detail"] == "Product not found"

    async def test_product_detail_has_lowest_price_and_store_count(
        self, client: AsyncClient
    ) -> None:
        """Product detail includes lowest_price and store_count derived from prices."""
        product = _make_product()
        store1_row = _make_price_row(
            product_id=product.id, store_name="Lidl", price=Decimal("1.50")
        )
        store2_row = _make_price_row(
            product_id=product.id, store_name="Kaufland", price=Decimal("1.80")
        )

        mock_db = AsyncMock()

        product_lookup = MagicMock()
        product_lookup.scalar_one_or_none.return_value = product

        price_result = MagicMock()
        price_result.all.return_value = [store1_row, store2_row]

        mock_db.execute = AsyncMock(
            side_effect=[product_lookup, price_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get(f"/products/{product.id}")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        data = response.json()
        assert data["store_count"] == 2
        assert float(data["lowest_price"]) == pytest.approx(1.50)

    async def test_invalid_uuid_returns_422(
        self, client: AsyncClient
    ) -> None:
        """A non-UUID path parameter triggers a 422 validation error."""
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()
        try:
            response = await client.get("/products/not-a-uuid")
        finally:
            app.dependency_overrides.pop(get_db_session, None)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /products/search?q=... — text search
# ---------------------------------------------------------------------------


class TestSearchProducts:
    """GET /products/search returns products matching the query."""

    async def test_search_returns_matching_products(
        self, client: AsyncClient
    ) -> None:
        """A search hit returns the matching product in the items list."""
        product = _make_product(name="Sunflower Oil", slug="sunflower-oil")
        enrich_row = _make_enrich_row(product.id)

        mock_db = AsyncMock()

        # FTS count (non-zero triggers FTS path)
        fts_count = MagicMock()
        fts_count.scalar_one.return_value = 1

        # FTS product results
        fts_products = MagicMock()
        fts_products.scalars.return_value.all.return_value = [product]

        # Enrichment
        enrich_result = MagicMock()
        enrich_result.all.return_value = [enrich_row]

        mock_db.execute = AsyncMock(
            side_effect=[fts_count, fts_products, enrich_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products/search?q=sunflower")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Sunflower Oil"

    async def test_search_falls_back_to_ilike_when_fts_empty(
        self, client: AsyncClient
    ) -> None:
        """When FTS finds nothing, ILIKE fallback is tried and returns results."""
        product = _make_product(name="Wheat Flour", slug="wheat-flour")
        enrich_row = _make_enrich_row(product.id)

        mock_db = AsyncMock()

        # FTS count = 0  -> triggers ILIKE fallback
        fts_count = MagicMock()
        fts_count.scalar_one.return_value = 0

        # ILIKE count
        ilike_count = MagicMock()
        ilike_count.scalar_one.return_value = 1

        # ILIKE products
        ilike_products = MagicMock()
        ilike_products.scalars.return_value.all.return_value = [product]

        # Enrichment
        enrich_result = MagicMock()
        enrich_result.all.return_value = [enrich_row]

        mock_db.execute = AsyncMock(
            side_effect=[fts_count, ilike_count, ilike_products, enrich_result]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products/search?q=flour")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Wheat Flour"

    async def test_search_empty_q_returns_422(
        self, client: AsyncClient
    ) -> None:
        """An empty search query string triggers a 422 validation error."""
        app.dependency_overrides[get_db_session] = lambda: AsyncMock()
        try:
            response = await client.get("/products/search?q=")
        finally:
            app.dependency_overrides.pop(get_db_session, None)
        assert response.status_code == 422

    async def test_search_no_results_returns_empty_list(
        self, client: AsyncClient
    ) -> None:
        """A query that matches nothing returns items=[] and total=0."""
        mock_db = AsyncMock()

        fts_count = MagicMock()
        fts_count.scalar_one.return_value = 0

        ilike_count = MagicMock()
        ilike_count.scalar_one.return_value = 0

        ilike_products = MagicMock()
        ilike_products.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(
            side_effect=[fts_count, ilike_count, ilike_products]
        )

        app.dependency_overrides[get_db_session] = lambda: mock_db

        try:
            response = await client.get("/products/search?q=zzznomatch")
        finally:
            app.dependency_overrides.pop(get_db_session, None)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
