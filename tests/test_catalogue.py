"""Unit tests for the product catalogue API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

from app.main import app
from app.models.category import Category
from app.models.product import Product, ProductStatus
from app.routers.catalogue import _build_tree, _collect_category_ids

# ---------------------------------------------------------------------------
# Fixtures
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
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    p = MagicMock(spec=Product)
    for k, v in defaults.items():
        setattr(p, k, v)
    return p


def _make_category(
    cat_id: uuid.UUID | None = None,
    name: str = "Cat",
    slug: str = "cat",
    parent_id: uuid.UUID | None = None,
) -> Category:
    """Create a mock Category instance."""
    c = MagicMock(spec=Category)
    c.id = cat_id or uuid.uuid4()
    c.name = name
    c.slug = slug
    c.parent_id = parent_id
    return c


# ---------------------------------------------------------------------------
# Pure-function tests (no DB required)
# ---------------------------------------------------------------------------


class TestBuildTree:
    """Tests for the _build_tree helper."""

    def test_empty_list_returns_empty_tree(self) -> None:
        """An empty category list yields an empty tree."""
        assert _build_tree([]) == []

    def test_single_root_category(self) -> None:
        """A single root category appears as a root node."""
        cat = _make_category(name="Root", slug="root")
        tree = _build_tree([cat])
        assert len(tree) == 1
        assert tree[0].name == "Root"
        assert tree[0].children == []

    def test_parent_child_nesting(self) -> None:
        """Child categories are nested under their parent."""
        root_id = uuid.uuid4()
        root = _make_category(cat_id=root_id, name="Root", slug="root")
        child = _make_category(name="Child", slug="child", parent_id=root_id)

        tree = _build_tree([root, child])
        assert len(tree) == 1
        assert tree[0].name == "Root"
        assert len(tree[0].children) == 1
        assert tree[0].children[0].name == "Child"

    def test_multiple_roots(self) -> None:
        """Multiple root categories are returned at the top level."""
        a = _make_category(name="A", slug="a")
        b = _make_category(name="B", slug="b")
        tree = _build_tree([a, b])
        assert len(tree) == 2

    def test_deep_nesting(self) -> None:
        """Three-level deep nesting works correctly."""
        root_id = uuid.uuid4()
        mid_id = uuid.uuid4()
        root = _make_category(cat_id=root_id, name="L1", slug="l1")
        mid = _make_category(cat_id=mid_id, name="L2", slug="l2", parent_id=root_id)
        leaf = _make_category(name="L3", slug="l3", parent_id=mid_id)

        tree = _build_tree([root, mid, leaf])
        assert len(tree) == 1
        assert len(tree[0].children) == 1
        assert len(tree[0].children[0].children) == 1
        assert tree[0].children[0].children[0].name == "L3"


class TestCollectCategoryIds:
    """Tests for the _collect_category_ids helper."""

    def test_single_category_no_children(self) -> None:
        """A leaf category returns only its own ID."""
        cat_id = uuid.uuid4()
        result = _collect_category_ids(cat_id, {})
        assert result == [cat_id]

    def test_collects_descendants(self) -> None:
        """All descendant IDs are collected recursively."""
        root_id = uuid.uuid4()
        child_id = uuid.uuid4()
        grandchild_id = uuid.uuid4()

        child = _make_category(cat_id=child_id, parent_id=root_id)
        grandchild = _make_category(cat_id=grandchild_id, parent_id=child_id)

        children_map: dict[uuid.UUID | None, list[Any]] = {
            root_id: [child],
            child_id: [grandchild],
        }

        result = _collect_category_ids(root_id, children_map)
        assert set(result) == {root_id, child_id, grandchild_id}


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemas:
    """Tests for Pydantic response schemas."""

    def test_paginated_response_serialization(self) -> None:
        """PaginatedResponse correctly serializes with generic items."""
        from app.schemas.catalogue import PaginatedResponse

        resp = PaginatedResponse[int](items=[1, 2, 3], total=10, limit=3, offset=0)
        data = resp.model_dump()
        assert data["items"] == [1, 2, 3]
        assert data["total"] == 10

    def test_product_list_item_optional_fields(self) -> None:
        """ProductListItem handles None optional fields."""
        from app.schemas.catalogue import ProductListItem

        item = ProductListItem(
            id=uuid.uuid4(),
            name="Test",
            slug="test",
            status="active",
        )
        assert item.lowest_price is None
        assert item.store_count == 0
        assert item.brand is None

    def test_category_node_recursive(self) -> None:
        """CategoryNode supports recursive children."""
        from app.schemas.catalogue import CategoryNode

        node = CategoryNode(
            id=uuid.uuid4(),
            name="Root",
            slug="root",
            children=[
                CategoryNode(
                    id=uuid.uuid4(),
                    name="Child",
                    slug="child",
                )
            ],
        )
        assert len(node.children) == 1
        assert node.children[0].name == "Child"

    def test_store_price_summary_from_attributes(self) -> None:
        """StorePriceSummary can be built from attribute-style access."""
        from app.schemas.catalogue import StorePriceSummary

        summary = StorePriceSummary(
            store_id=uuid.uuid4(),
            store_name="Lidl",
            store_slug="lidl",
            price=Decimal("2.99"),
            currency="EUR",
            recorded_at=datetime.now(tz=UTC),
        )
        assert summary.price == Decimal("2.99")
        assert summary.currency == "EUR"


# ---------------------------------------------------------------------------
# Router registration test
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    """Verify catalogue routes are registered on the app."""

    def test_products_route_exists(self) -> None:
        """GET /products is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products" in routes

    def test_products_search_route_exists(self) -> None:
        """GET /products/search is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products/search" in routes

    def test_product_detail_route_exists(self) -> None:
        """GET /products/{product_id} is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/products/{product_id}" in routes

    def test_categories_route_exists(self) -> None:
        """GET /categories is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/categories" in routes

    def test_category_products_route_exists(self) -> None:
        """GET /categories/{category_id}/products is a registered route."""
        routes = [r.path for r in app.routes]
        assert "/categories/{category_id}/products" in routes
