"""Pydantic schemas for the browse API endpoints."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /browse — category hierarchy
# ---------------------------------------------------------------------------


class BrandEntry(BaseModel):
    """A single brand within a product type group.

    Attributes:
        brand: Brand name (or 'Собствена марка' for own-label).
        price_min: Lowest price observed for this brand.
        price_max: Highest price observed.
        max_discount: Largest active discount percentage, if any.
        store_count: Number of distinct stores carrying this brand.
        cheapest_store: Name of the store with the lowest price.
    """

    brand: str
    price_min: float
    price_max: float
    max_discount: int | None = None
    store_count: int = 0
    cheapest_store: str | None = None


class ProductTypeEntry(BaseModel):
    """A product type group within a sub-category.

    Attributes:
        product_type: Product type label (or 'Общо' for unspecified).
        brands: Brands within this type.
        price_min: Aggregated minimum price across brands.
        price_max: Aggregated maximum price.
    """

    product_type: str
    brands: list[BrandEntry] = Field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0


class SubCategoryEntry(BaseModel):
    """A sub-category within a top-level category.

    Attributes:
        category: Sub-category name.
        product_types: Product type groups in this sub-category.
        price_min: Aggregated minimum price.
        price_max: Aggregated maximum price.
    """

    category: str
    product_types: list[ProductTypeEntry] = Field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0


class TopCategoryEntry(BaseModel):
    """A top-level category with nested hierarchy.

    Attributes:
        top_category: Top-level category name.
        sub_categories: Sub-categories in this group.
        price_min: Aggregated minimum price.
        price_max: Aggregated maximum price.
    """

    top_category: str
    sub_categories: list[SubCategoryEntry] = Field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0


class BrowseResponse(BaseModel):
    """Response for GET /browse — structured category hierarchy.

    Attributes:
        top_categories: Sorted list of top-level categories.
    """

    top_categories: list[TopCategoryEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /browse/deals — best deals
# ---------------------------------------------------------------------------


class DealItem(BaseModel):
    """A single deal item with discount information.

    Attributes:
        product_name: Display name of the product.
        brand: Brand name, or None.
        store: Name of the store offering this deal.
        price: Current discounted price.
        original_price: Pre-discount price, or None.
        discount_percent: Discount percentage.
        top_category: Top-level category, or None.
        category: Sub-category, or None.
        image_url: Product image URL, or None.
    """

    product_name: str
    brand: str | None = None
    store: str
    price: Decimal
    original_price: Decimal | None = None
    discount_percent: int
    top_category: str | None = None
    category: str | None = None
    image_url: str | None = None


class DealsResponse(BaseModel):
    """Response for GET /browse/deals.

    Attributes:
        items: List of deal items sorted by discount_percent DESC.
        total: Total number of matching deals (before limit).
    """

    items: list[DealItem] = Field(default_factory=list)
    total: int = 0
