"""Unit tests for the price comparison API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.schemas.comparison import (
    ComparisonResponse,
    SearchCompareItem,
    SearchCompareResponse,
    StoreComparison,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_product(**overrides: Any) -> Product:
    """Create a mock Product instance with sensible defaults."""
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Test Product",
        "slug": "test-product",
        "brand": "TestBrand",
        "category_id": None,
        "image_url": None,
        "barcode": None,
        "status": ProductStatus.ACTIVE,
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": datetime.now(tz=timezone.utc),
    }
    defaults.update(overrides)
    p = MagicMock(spec=Product)
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestStoreComparisonSchema:
    """Tests for the StoreComparison Pydantic model."""

    def test_store_comparison_fields(self) -> None:
        """StoreComparison schema stores all required fields."""
        sc = StoreComparison(
            store_id=uuid.uuid4(),
            store_name="Lidl",
            store_slug="lidl",
            logo_url="https://example.com/lidl.png",
            price=Decimal("2.99"),
            currency="BGN",
            unit=None,
            last_scraped_at=datetime.now(tz=timezone.utc),
            source="web",
            price_diff_pct=0.0,
        )
        assert sc.price == Decimal("2.99")
        assert sc.price_diff_pct == 0.0
        assert sc.unit is None
        assert sc.source == "web"

    def test_store_comparison_with_logo_none(self) -> None:
        """StoreComparison allows None for logo_url."""
        sc = StoreComparison(
            store_id=uuid.uuid4(),
            store_name="Kaufland",
            store_slug="kaufland",
            logo_url=None,
            price=Decimal("3.49"),
            currency="BGN",
            unit=None,
            last_scraped_at=datetime.now(tz=timezone.utc),
            source="brochure",
            price_diff_pct=16.7,
        )
        assert sc.logo_url is None
        assert sc.source == "brochure"


class TestComparisonResponse:
    """Tests for the ComparisonResponse Pydantic model."""

    def test_empty_comparisons(self) -> None:
        """ComparisonResponse handles zero comparisons (no stores carry it)."""
        resp = ComparisonResponse(
            product_id=uuid.uuid4(),
            product_name="Milk",
            product_slug="milk",
            comparisons=[],
        )
        assert resp.comparisons == []

    def test_comparisons_sorted_cheapest_first(self) -> None:
        """Verify that comparisons can be provided sorted cheapest first."""
        now = datetime.now(tz=timezone.utc)
        cheap = StoreComparison(
            store_id=uuid.uuid4(),
            store_name="Lidl",
            store_slug="lidl",
            logo_url=None,
            price=Decimal("1.50"),
            currency="BGN",
            unit=None,
            last_scraped_at=now,
            source="web",
            price_diff_pct=0.0,
        )
        expensive = StoreComparison(
            store_id=uuid.uuid4(),
            store_name="Billa",
            store_slug="billa",
            logo_url=None,
            price=Decimal("2.00"),
            currency="BGN",
            unit=None,
            last_scraped_at=now,
            source="web",
            price_diff_pct=33.3,
        )
        resp = ComparisonResponse(
            product_id=uuid.uuid4(),
            product_name="Milk",
            product_slug="milk",
            comparisons=[cheap, expensive],
        )
        assert resp.comparisons[0].price < resp.comparisons[1].price
        assert resp.comparisons[0].price_diff_pct == 0.0


class TestSearchCompareSchemas:
    """Tests for SearchCompareItem and SearchCompareResponse."""

    def test_search_compare_item_fields(self) -> None:
        """SearchCompareItem stores all required fields."""
        item = SearchCompareItem(
            product_id=uuid.uuid4(),
            product_name="Bread",
            product_slug="bread",
            brand="Dobrudja",
            cheapest_store_name="Lidl",
            cheapest_store_slug="lidl",
            cheapest_price=Decimal("1.29"),
            currency="BGN",
            store_count=3,
        )
        assert item.cheapest_price == Decimal("1.29")
        assert item.store_count == 3

    def test_search_compare_response_empty(self) -> None:
        """SearchCompareResponse handles zero results."""
        resp = SearchCompareResponse(query="nonexistent", results=[])
        assert resp.results == []
        assert resp.query == "nonexistent"


# ---------------------------------------------------------------------------
# Price diff calculation tests
# ---------------------------------------------------------------------------


class TestPriceDiffPctCalculation:
    """Tests for the price_diff_pct formula."""

    def test_cheapest_gets_zero(self) -> None:
        """The cheapest store should always have price_diff_pct = 0.0."""
        min_price = Decimal("2.00")
        price = Decimal("2.00")
        diff_pct = round(float((price - min_price) / min_price * 100), 1)
        assert diff_pct == 0.0

    def test_50_percent_more_expensive(self) -> None:
        """A store 50% above the cheapest price gets 50.0."""
        min_price = Decimal("2.00")
        price = Decimal("3.00")
        diff_pct = round(float((price - min_price) / min_price * 100), 1)
        assert diff_pct == 50.0

    def test_small_difference(self) -> None:
        """A small price difference is calculated correctly."""
        min_price = Decimal("1.50")
        price = Decimal("1.55")
        diff_pct = round(float((price - min_price) / min_price * 100), 1)
        assert diff_pct == 3.3

    def test_100_percent_more_expensive(self) -> None:
        """Double the price yields 100.0 percent difference."""
        min_price = Decimal("5.00")
        price = Decimal("10.00")
        diff_pct = round(float((price - min_price) / min_price * 100), 1)
        assert diff_pct == 100.0

    def test_same_price_all_stores(self) -> None:
        """When all stores have the same price, all get 0.0."""
        min_price = Decimal("4.99")
        for price in [Decimal("4.99"), Decimal("4.99"), Decimal("4.99")]:
            diff_pct = round(float((price - min_price) / min_price * 100), 1)
            assert diff_pct == 0.0


# ---------------------------------------------------------------------------
# Partial results tests
# ---------------------------------------------------------------------------


class TestPartialResults:
    """Tests for partial results when not all stores carry a product."""

    def test_single_store_comparison(self) -> None:
        """A product at only one store returns one comparison with 0.0 diff."""
        now = datetime.now(tz=timezone.utc)
        resp = ComparisonResponse(
            product_id=uuid.uuid4(),
            product_name="Rare Item",
            product_slug="rare-item",
            comparisons=[
                StoreComparison(
                    store_id=uuid.uuid4(),
                    store_name="Lidl",
                    store_slug="lidl",
                    logo_url=None,
                    price=Decimal("9.99"),
                    currency="BGN",
                    unit=None,
                    last_scraped_at=now,
                    source="web",
                    price_diff_pct=0.0,
                ),
            ],
        )
        assert len(resp.comparisons) == 1
        assert resp.comparisons[0].price_diff_pct == 0.0

    def test_two_of_three_stores(self) -> None:
        """Product at 2 of 3 stores returns only 2 comparisons."""
        now = datetime.now(tz=timezone.utc)
        comparisons = [
            StoreComparison(
                store_id=uuid.uuid4(),
                store_name="Lidl",
                store_slug="lidl",
                logo_url=None,
                price=Decimal("2.50"),
                currency="BGN",
                unit=None,
                last_scraped_at=now,
                source="web",
                price_diff_pct=0.0,
            ),
            StoreComparison(
                store_id=uuid.uuid4(),
                store_name="Billa",
                store_slug="billa",
                logo_url=None,
                price=Decimal("3.00"),
                currency="BGN",
                unit=None,
                last_scraped_at=now,
                source="brochure",
                price_diff_pct=20.0,
            ),
        ]
        resp = ComparisonResponse(
            product_id=uuid.uuid4(),
            product_name="Yogurt",
            product_slug="yogurt",
            comparisons=comparisons,
        )
        assert len(resp.comparisons) == 2
        # Only 2 stores, not 3
        prices = [c.price for c in resp.comparisons]
        assert prices == sorted(prices)


# ---------------------------------------------------------------------------
# Route registration tests
# ---------------------------------------------------------------------------


class TestComparisonRouteRegistration:
    """Verify comparison routes are registered on the app."""

    def test_product_compare_route_exists(self) -> None:
        """GET /products/{product_id}/compare is a registered route."""
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/products/{product_id}/compare" in routes

    def test_search_compare_route_exists(self) -> None:
        """GET /products/compare is a registered route."""
        from app.main import app

        routes = [r.path for r in app.routes]
        assert "/products/compare" in routes


# ---------------------------------------------------------------------------
# 404 test
# ---------------------------------------------------------------------------


class TestCompare404:
    """Tests for 404 when product not found."""

    def test_comparison_response_requires_valid_product(self) -> None:
        """ComparisonResponse can be constructed for any product_id (schema level).

        The actual 404 is raised at the endpoint level when the DB lookup
        returns None.  At the schema level we just verify the model accepts
        any UUID.
        """
        fake_id = uuid.uuid4()
        resp = ComparisonResponse(
            product_id=fake_id,
            product_name="Ghost",
            product_slug="ghost",
            comparisons=[],
        )
        assert resp.product_id == fake_id
