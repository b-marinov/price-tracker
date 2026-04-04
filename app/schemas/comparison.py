"""Pydantic schemas for the price comparison API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class StoreComparison(BaseModel):
    """Price comparison entry for a single store.

    Attributes:
        store_id: Unique identifier of the store.
        store_name: Display name of the store.
        store_slug: URL-friendly store identifier.
        logo_url: URL to the store's logo image, if available.
        price: Latest recorded price at this store.
        currency: ISO 4217 currency code.
        unit: Unit extracted from product name (future enhancement).
        last_scraped_at: Timestamp of the most recent price observation.
        source: How the price was obtained (web or brochure).
        price_diff_pct: Percentage above the cheapest price (0.0 for cheapest).
    """

    model_config = ConfigDict(from_attributes=True)

    store_id: uuid.UUID
    store_name: str
    store_slug: str
    logo_url: str | None = None
    price: Decimal
    currency: str
    unit: str | None = None
    last_scraped_at: datetime
    source: str
    price_diff_pct: float


class ComparisonResponse(BaseModel):
    """Full comparison response for a single product across stores.

    Attributes:
        product_id: Unique identifier of the product.
        product_name: Display name of the product.
        product_slug: URL-friendly product identifier.
        comparisons: Per-store price comparisons, sorted cheapest first.
    """

    product_id: uuid.UUID
    product_name: str
    product_slug: str
    comparisons: list[StoreComparison]


class SearchCompareItem(BaseModel):
    """A single product match with its cheapest store price.

    Attributes:
        product_id: Unique identifier of the product.
        product_name: Display name of the product.
        product_slug: URL-friendly product identifier.
        brand: Brand or manufacturer name.
        cheapest_store_name: Name of the store with the lowest price.
        cheapest_store_slug: URL-friendly identifier of the cheapest store.
        cheapest_price: The lowest current price found.
        currency: ISO 4217 currency code.
        store_count: Number of stores carrying this product.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    product_name: str
    product_slug: str
    brand: str | None = None
    cheapest_store_name: str
    cheapest_store_slug: str
    cheapest_price: Decimal
    currency: str
    store_count: int


class SearchCompareResponse(BaseModel):
    """Response for search-driven price comparison.

    Attributes:
        query: The original search query string.
        results: Top matching products with their cheapest prices.
    """

    query: str
    results: list[SearchCompareItem]
