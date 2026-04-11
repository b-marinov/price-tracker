"""Browse API — hierarchical view of top-categories, sub-categories, product types, and brands.

Provides a single ``GET /browse`` endpoint that returns a fully nested
structure of top_category -> category -> product_type -> brand with
aggregated price and discount statistics drawn directly from the prices table.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.database import get_db_session
from app.models.price import Price
from app.models.product import Product
from app.models.store import Store

router = APIRouter(prefix="/browse", tags=["browse"])

# Type alias for the injected session
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# Display label used when the brand column is NULL
_NULL_BRAND_LABEL = "Собствена марка"
# Display label used when the product_type column is NULL
_NULL_PRODUCT_TYPE_LABEL = "Общо"


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class BrandEntry(BaseModel):
    """Aggregated price statistics for a single brand within a product type.

    Attributes:
        brand: Brand name, or "Собствена марка" for unbranded products.
        price_min: Lowest observed price across all stores.
        price_max: Highest observed price across all stores.
        cheapest_store: Name of the store that carries this brand at the
            lowest price.
        max_discount: Largest discount percentage seen for this brand.
        store_count: Number of distinct stores stocking this brand.
    """

    brand: str | None
    price_min: float
    price_max: float
    cheapest_store: str | None
    max_discount: int | None
    store_count: int


class ProductTypeEntry(BaseModel):
    """Aggregated statistics for a product type with its brand breakdown.

    Attributes:
        product_type: Product type name (e.g. "Шампоан", "Крем"), or
            "Общо" when the LLM did not extract a specific type.
        price_min: Lowest price across all brands in this product type.
        price_max: Highest price across all brands in this product type.
        brand_count: Number of distinct brands present.
        brands: List of BrandEntry objects sorted by price_min ascending.
    """

    product_type: str
    price_min: float
    price_max: float
    brand_count: int
    brands: list[BrandEntry]


class SubCategoryEntry(BaseModel):
    """Aggregated statistics for a sub-category with its product type breakdown.

    Attributes:
        category: Sub-category name.
        price_min: Lowest price across all product types in this sub-category.
        price_max: Highest price across all product types in this sub-category.
        product_type_count: Number of distinct product types present.
        product_types: List of ProductTypeEntry objects sorted alphabetically.
    """

    category: str
    price_min: float
    price_max: float
    product_type_count: int
    product_types: list[ProductTypeEntry]


class TopCategoryEntry(BaseModel):
    """Aggregated statistics for a top-level category with its sub-category breakdown.

    Attributes:
        top_category: Top-level category name.
        price_min: Lowest price anywhere in this top-level category.
        price_max: Highest price anywhere in this top-level category.
        sub_category_count: Number of distinct sub-categories present.
        sub_categories: List of SubCategoryEntry objects sorted alphabetically.
    """

    top_category: str
    price_min: float
    price_max: float
    sub_category_count: int
    sub_categories: list[SubCategoryEntry]


class BrowseResponse(BaseModel):
    """Top-level response envelope for GET /browse.

    Attributes:
        top_categories: List of TopCategoryEntry objects sorted alphabetically.
    """

    top_categories: list[TopCategoryEntry]


class DealItem(BaseModel):
    """A single deal item returned by GET /browse/deals.

    Attributes:
        product_name: Name of the product.
        brand: Brand name, or None if unbranded.
        store: Name of the store carrying this deal.
        price: Current discounted price.
        original_price: Pre-discount price, or None if not recorded.
        discount_percent: Discount percentage (>0).
        top_category: Top-level category group, or None if not classified.
        category: Sub-category, or None if not classified.
        image_url: Product image URL, or None if unavailable.
    """

    product_name: str
    brand: str | None
    store: str
    price: float
    original_price: float | None
    discount_percent: int
    top_category: str | None
    category: str | None
    image_url: str | None


class DealsResponse(BaseModel):
    """Response envelope for GET /browse/deals.

    Attributes:
        items: List of DealItem objects sorted by discount_percent desc, price asc.
        total: Total number of matching rows before the limit is applied.
    """

    items: list[DealItem]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cheapest_store_subquery() -> Subquery:
    """Build a subquery returning the store name for the minimum price per group.

    Groups by (top_category, category, product_type, brand) and returns the
    store name associated with the row that has the lowest price for that group.

    Returns:
        A SQLAlchemy subquery with columns:
        top_category, category, product_type, brand, cheapest_store.
    """
    ranked = (
        select(
            Price.top_category,
            Price.category,
            Price.product_type,
            Price.brand,
            Store.name.label("store_name"),
            func.row_number()
            .over(
                partition_by=[
                    Price.top_category,
                    Price.category,
                    Price.product_type,
                    Price.brand,
                ],
                order_by=Price.price.asc(),
            )
            .label("rn"),
        )
        .join(Store, Store.id == Price.store_id)
        .where(Price.top_category.is_not(None))
        .where(Price.category.is_not(None))
        .subquery("ranked")
    )

    return (
        select(
            ranked.c.top_category,
            ranked.c.category,
            ranked.c.product_type,
            ranked.c.brand,
            ranked.c.store_name.label("cheapest_store"),
        )
        .where(ranked.c.rn == 1)
        .subquery("cheapest_store_sub")
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("", response_model=BrowseResponse)
async def browse(db: DbSession) -> BrowseResponse:
    """Return a hierarchical view of all products organised by category.

    Builds a four-level hierarchy:
        top_category -> category (sub-category) -> product_type -> brand.

    Each level is annotated with aggregated price statistics (min/max price,
    max discount, store count).

    Rows where top_category or category is NULL are excluded.  Rows where
    product_type is NULL are labelled "Общо".  Rows where brand is NULL are
    labelled "Собствена марка" (own-brand / private label).

    The response is sorted:
    - top_categories: alphabetically by top_category
    - sub_categories: alphabetically by category
    - product_types: alphabetically by product_type
    - brands: by price_min ascending

    Args:
        db: Async database session (injected by FastAPI).

    Returns:
        BrowseResponse containing the full four-level hierarchy.
    """
    cheapest_sub = _cheapest_store_subquery()

    # Main aggregation: one row per (top_category, category, product_type, brand)
    stmt = (
        select(
            Price.top_category,
            Price.category,
            Price.product_type,
            Price.brand,
            func.min(Price.price).label("price_min"),
            func.max(Price.price).label("price_max"),
            func.max(Price.discount_percent).label("max_discount"),
            func.count(func.distinct(Price.store_id)).label("store_count"),
            cheapest_sub.c.cheapest_store,
        )
        .outerjoin(
            cheapest_sub,
            (Price.top_category == cheapest_sub.c.top_category)
            & (Price.category == cheapest_sub.c.category)
            & (
                (Price.product_type == cheapest_sub.c.product_type)
                | (Price.product_type.is_(None) & cheapest_sub.c.product_type.is_(None))
            )
            & (
                (Price.brand == cheapest_sub.c.brand)
                | (Price.brand.is_(None) & cheapest_sub.c.brand.is_(None))
            ),
        )
        .where(Price.top_category.is_not(None))
        .where(Price.category.is_not(None))
        .group_by(
            Price.top_category,
            Price.category,
            Price.product_type,
            Price.brand,
            cheapest_sub.c.cheapest_store,
        )
    )

    rows = (await db.execute(stmt)).all()

    # Build the nested structure in Python
    # top_map[top_category][category][product_type] -> [BrandEntry, ...]
    top_map: dict[str, dict[str, dict[str, list[BrandEntry]]]] = {}

    for row in rows:
        top_cat: str = row.top_category
        sub_cat: str = row.category
        pt_label: str = row.product_type if row.product_type else _NULL_PRODUCT_TYPE_LABEL
        brand_label: str | None = row.brand if row.brand is not None else _NULL_BRAND_LABEL

        brand_entry = BrandEntry(
            brand=brand_label,
            price_min=float(row.price_min),
            price_max=float(row.price_max),
            cheapest_store=row.cheapest_store,
            max_discount=row.max_discount,
            store_count=row.store_count,
        )

        top_map.setdefault(top_cat, {})
        top_map[top_cat].setdefault(sub_cat, {})
        top_map[top_cat][sub_cat].setdefault(pt_label, [])
        top_map[top_cat][sub_cat][pt_label].append(brand_entry)

    # Assemble the final response, applying sort rules at each level
    top_categories: list[TopCategoryEntry] = []

    for top_cat in sorted(top_map.keys()):
        sub_map = top_map[top_cat]
        sub_categories: list[SubCategoryEntry] = []

        for sub_cat in sorted(sub_map.keys()):
            pt_map = sub_map[sub_cat]
            product_types: list[ProductTypeEntry] = []

            for pt_name in sorted(pt_map.keys()):
                brands = sorted(pt_map[pt_name], key=lambda b: b.price_min)
                pt_entry = ProductTypeEntry(
                    product_type=pt_name,
                    price_min=min(b.price_min for b in brands),
                    price_max=max(b.price_max for b in brands),
                    brand_count=len(brands),
                    brands=brands,
                )
                product_types.append(pt_entry)

            sub_entry = SubCategoryEntry(
                category=sub_cat,
                price_min=min(pt.price_min for pt in product_types),
                price_max=max(pt.price_max for pt in product_types),
                product_type_count=len(product_types),
                product_types=product_types,
            )
            sub_categories.append(sub_entry)

        top_entry = TopCategoryEntry(
            top_category=top_cat,
            price_min=min(s.price_min for s in sub_categories),
            price_max=max(s.price_max for s in sub_categories),
            sub_category_count=len(sub_categories),
            sub_categories=sub_categories,
        )
        top_categories.append(top_entry)

    return BrowseResponse(top_categories=top_categories)


@router.get("/deals", response_model=DealsResponse)
async def get_deals(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    top_category: str | None = Query(default=None),
) -> DealsResponse:
    """Return products currently on sale, ordered by discount descending.

    Joins Price to Product (for name) and Store (for store name).  Only rows
    where ``discount_percent`` is non-NULL and greater than zero are included.
    An optional ``top_category`` filter narrows results to a single top-level
    category.  Results are ordered by discount_percent DESC then price ASC and
    capped at ``limit`` rows.

    A separate count query returns the total number of matching rows so the
    caller can implement pagination if desired.

    Args:
        db: Async database session (injected by FastAPI).
        limit: Maximum number of deal rows to return (1-200, default 50).
        top_category: When provided, restrict results to this top-level
            category value.

    Returns:
        DealsResponse with the deal items and the total matching row count.
    """
    # Base filter conditions shared by both the data and count queries
    base_filters = [
        Price.discount_percent.is_not(None),
        Price.discount_percent > 0,
    ]
    if top_category is not None:
        base_filters.append(Price.top_category == top_category)

    # Count query — total matching rows before limit
    count_stmt = (
        select(func.count())
        .select_from(Price)
        .where(*base_filters)
    )
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Data query — join to Product and Store for display names
    data_stmt = (
        select(
            Product.name.label("product_name"),
            Price.brand,
            Store.name.label("store_name"),
            Price.price,
            Price.original_price,
            Price.discount_percent,
            Price.top_category,
            Price.category,
            Price.image_url,
        )
        .join(Product, Product.id == Price.product_id)
        .join(Store, Store.id == Price.store_id)
        .where(*base_filters)
        .order_by(Price.discount_percent.desc(), Price.price.asc())
        .limit(limit)
    )

    rows = (await db.execute(data_stmt)).all()

    items: list[DealItem] = [
        DealItem(
            product_name=row.product_name,
            brand=row.brand,
            store=row.store_name,
            price=float(row.price),
            original_price=float(row.original_price) if row.original_price is not None else None,
            discount_percent=row.discount_percent,
            top_category=row.top_category,
            category=row.category,
            image_url=row.image_url,
        )
        for row in rows
    ]

    return DealsResponse(items=items, total=total)
