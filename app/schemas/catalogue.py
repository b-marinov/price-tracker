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
