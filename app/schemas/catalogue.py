"""Pydantic schemas for the product catalogue API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Pagination wrapper
# ---------------------------------------------------------------------------


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response envelope.

    Attributes:
        items: List of result objects for the current page.
        total: Total number of matching records.
        limit: Maximum items per page.
        offset: Number of items skipped.
    """

    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Store summary (used inside product responses)
# ---------------------------------------------------------------------------


class StorePriceSummary(BaseModel):
    """Price information for a single store.

    Attributes:
        store_id: Unique identifier of the store.
        store_name: Display name of the store.
        store_slug: URL-friendly store identifier.
        price: Latest recorded price at this store.
        currency: ISO 4217 currency code.
        recorded_at: Timestamp of the price observation.
    """

    model_config = ConfigDict(from_attributes=True)

    store_id: uuid.UUID
    store_name: str
    store_slug: str
    price: Decimal
    currency: str
    unit: str | None = None
    pack_info: str | None = None
    pack_type: str | None = None
    generic_pack: str | None = None
    brand: str | None = None
    recorded_at: datetime


# ---------------------------------------------------------------------------
# Product schemas
# ---------------------------------------------------------------------------


class ProductListItem(BaseModel):
    """Compact product representation for list endpoints.

    Attributes:
        id: Unique product identifier.
        name: Display name.
        slug: URL-friendly identifier.
        brand: Brand or manufacturer name.
        category_id: FK to the product category.
        image_url: URL to the product image.
        barcode: EAN/UPC barcode string.
        status: Current product status.
        lowest_price: Current lowest price across all stores.
        store_count: Number of stores carrying this product.
        last_updated: Most recent price observation timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    brand: str | None = None
    pack_info: str | None = None
    pack_type: str | None = None
    generic_pack: str | None = None
    additional_info: str | None = None
    category_id: uuid.UUID | None = None
    image_url: str | None = None
    barcode: str | None = None
    status: str
    lowest_price: Decimal | None = None
    store_count: int = 0
    last_updated: datetime | None = None


class ProductDetail(ProductListItem):
    """Full product detail with per-store price breakdown.

    Attributes:
        prices: List of current prices at each store.
    """

    prices: list[StorePriceSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Product family (catalog-name grouping) schemas
# ---------------------------------------------------------------------------


class ProductFamilyListItem(BaseModel):
    """A catalog product name with aggregated stats across all variants.

    One entry per catalog.yaml product name (e.g. one "Бира" entry that
    covers all brands/packs/stores), instead of one entry per
    (name, brand, pack) variant.
    """

    name: str
    name_slug: str
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    image_url: str | None = None
    brand_count: int = 0
    pack_count: int = 0
    store_count: int = 0
    variant_count: int = 0
    lowest_price: Decimal | None = None
    lowest_price_per_unit: Decimal | None = None
    per_unit_basis: str | None = None
    last_updated: datetime | None = None


class ProductFamilyVariant(BaseModel):
    """A single (brand × pack × store) variant with its current price."""

    product_id: uuid.UUID
    brand: str | None = None
    pack_info: str | None = None
    generic_pack: str | None = None
    pack_type: str | None = None
    store_id: uuid.UUID
    store_name: str
    store_slug: str
    price: Decimal
    price_per_unit: Decimal | None = None
    per_unit_basis: str | None = None
    currency: str = "EUR"
    unit: str | None = None
    original_price: Decimal | None = None
    discount_percent: float | None = None
    image_url: str | None = None
    recorded_at: datetime


class ProductFamilyDetail(BaseModel):
    """Full breakdown of a catalog product name across every variant."""

    name: str
    name_slug: str
    category_id: uuid.UUID | None = None
    category_name: str | None = None
    image_url: str | None = None
    brand_count: int = 0
    pack_count: int = 0
    store_count: int = 0
    variant_count: int = 0
    lowest_price: Decimal | None = None
    lowest_price_per_unit: Decimal | None = None
    per_unit_basis: str | None = None
    brands: list[str] = Field(default_factory=list)
    variants: list[ProductFamilyVariant] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Category schemas
# ---------------------------------------------------------------------------


class CategoryNode(BaseModel):
    """A single node in the category tree.

    Attributes:
        id: Unique category identifier.
        name: Display name.
        slug: URL-friendly identifier.
        parent_id: FK to the parent category (None for root).
        children: Nested child categories.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    parent_id: uuid.UUID | None = None
    children: list[CategoryNode] = Field(default_factory=list)
