"""Browse API endpoints — category hierarchy and best deals.

Provides two main endpoints:
- GET /browse — structured category hierarchy with price aggregations
- GET /browse/deals — top discounts across all stores
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.schemas.browse import (
    BrandEntry,
    BrowseResponse,
    DealItem,
    DealsResponse,
    ProductTypeEntry,
    SubCategoryEntry,
    TopCategoryEntry,
)

router = APIRouter(prefix="/browse", tags=["browse"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# Label defaults for null values (Bulgarian UI)
_DEFAULT_PRODUCT_TYPE = "Общо"
_DEFAULT_BRAND = "Собствена марка"


# ---------------------------------------------------------------------------
# GET /browse — category hierarchy
# ---------------------------------------------------------------------------


@router.get("", response_model=BrowseResponse)
async def browse_categories(db: DbSession) -> BrowseResponse:
    """Return a structured category hierarchy with price aggregations.

    Args:
        db: Async database session.

    Returns:
        BrowseResponse with nested top_categories → sub_categories →
        product_types → brands.
    """
    # Latest price per product-store
    latest = (
        select(
            Price.product_id,
            Price.store_id,
            func.max(Price.recorded_at).label("max_recorded_at"),
        )
        .group_by(Price.product_id, Price.store_id)
        .subquery("latest")
    )

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
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Product, Price.product_id == Product.id)
        .where(Product.status == ProductStatus.ACTIVE)
        .where(Price.top_category.is_not(None))
        .group_by(
            Price.top_category,
            Price.category,
            Price.product_type,
            Price.brand,
        )
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Build hierarchy: top_category → category → product_type → brand
    # Using nested defaultdicts for grouping
    hierarchy: dict[str, dict[str, dict[str, list[BrandEntry]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # Track price bounds per group for aggregation
    price_bounds: dict[str, dict[str, dict[str, tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: (float("inf"), float("-inf"))))
    )

    for row in rows:
        top_cat = row.top_category or _DEFAULT_PRODUCT_TYPE
        sub_cat = row.category or _DEFAULT_PRODUCT_TYPE
        prod_type = row.product_type if row.product_type is not None else _DEFAULT_PRODUCT_TYPE
        brand_name = row.brand if row.brand is not None else _DEFAULT_BRAND

        p_min = float(row.price_min)
        p_max = float(row.price_max)

        entry = BrandEntry(
            brand=brand_name,
            price_min=p_min,
            price_max=p_max,
            max_discount=row.max_discount,
            store_count=row.store_count,
            cheapest_store=getattr(row, "cheapest_store", None),
        )
        hierarchy[top_cat][sub_cat][prod_type].append(entry)

        # Update bounds
        cur = price_bounds[top_cat][sub_cat][prod_type]
        price_bounds[top_cat][sub_cat][prod_type] = (
            min(cur[0], p_min),
            max(cur[1], p_max),
        )

    # Assemble response
    top_categories: list[TopCategoryEntry] = []
    for top_cat in sorted(hierarchy.keys()):
        sub_entries: list[SubCategoryEntry] = []
        top_min, top_max = float("inf"), float("-inf")

        for sub_cat in sorted(hierarchy[top_cat].keys()):
            pt_entries: list[ProductTypeEntry] = []
            sub_min, sub_max = float("inf"), float("-inf")

            for prod_type in sorted(hierarchy[top_cat][sub_cat].keys()):
                brands = hierarchy[top_cat][sub_cat][prod_type]
                bounds = price_bounds[top_cat][sub_cat][prod_type]
                pt_entries.append(ProductTypeEntry(
                    product_type=prod_type,
                    brands=brands,
                    price_min=bounds[0],
                    price_max=bounds[1],
                ))
                sub_min = min(sub_min, bounds[0])
                sub_max = max(sub_max, bounds[1])

            sub_entries.append(SubCategoryEntry(
                category=sub_cat,
                product_types=pt_entries,
                price_min=sub_min,
                price_max=sub_max,
            ))
            top_min = min(top_min, sub_min)
            top_max = max(top_max, sub_max)

        top_categories.append(TopCategoryEntry(
            top_category=top_cat,
            sub_categories=sub_entries,
            price_min=top_min if top_min != float("inf") else 0.0,
            price_max=top_max if top_max != float("-inf") else 0.0,
        ))

    return BrowseResponse(top_categories=top_categories)


# ---------------------------------------------------------------------------
# GET /browse/deals — best deals
# ---------------------------------------------------------------------------


@router.get("/deals", response_model=DealsResponse)
async def browse_deals(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    top_category: str | None = Query(default=None),
) -> DealsResponse:
    """Return products with the highest active discounts.

    Args:
        db: Async database session.
        limit: Maximum number of deal items to return (1-200).
        top_category: Optional filter by top-level category.

    Returns:
        DealsResponse with deal items and total matching count.
    """
    # Latest price per product-store
    latest = (
        select(
            Price.product_id,
            Price.store_id,
            func.max(Price.recorded_at).label("max_recorded_at"),
        )
        .group_by(Price.product_id, Price.store_id)
        .subquery("latest")
    )

    # Base conditions: active products with a discount
    base_conditions = [
        Product.status == ProductStatus.ACTIVE,
        Price.discount_percent.is_not(None),
        Price.discount_percent > 0,
    ]
    if top_category is not None:
        base_conditions.append(Price.top_category == top_category)

    # Count query
    count_stmt = (
        select(func.count())
        .select_from(Price)
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Product, Price.product_id == Product.id)
        .join(Store, Price.store_id == Store.id)
        .where(*base_conditions)
    )

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Data query
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
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Product, Price.product_id == Product.id)
        .join(Store, Price.store_id == Store.id)
        .where(*base_conditions)
        .order_by(Price.discount_percent.desc())
        .limit(limit)
    )

    data_result = await db.execute(data_stmt)
    rows = data_result.all()

    items = [
        DealItem(
            product_name=row.product_name,
            brand=row.brand,
            store=row.store_name,
            price=row.price,
            original_price=row.original_price,
            discount_percent=row.discount_percent,
            top_category=row.top_category,
            category=row.category,
            image_url=row.image_url,
        )
        for row in rows
    ]

    return DealsResponse(items=items, total=total)
