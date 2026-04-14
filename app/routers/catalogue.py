"""Product catalogue API endpoints.

Provides browsing, searching, and category navigation for the product
catalogue.  All list endpoints return paginated responses with price
summary data (lowest price, store count, last updated).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.database import get_db_session
from app.models.category import Category
from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.schemas.catalogue import (
    CategoryNode,
    PaginatedResponse,
    ProductDetail,
    ProductListItem,
    StorePriceSummary,
)
from app.schemas.comparison import (
    ComparisonResponse,
    SearchCompareItem,
    SearchCompareResponse,
    StoreComparison,
)

router = APIRouter(prefix="/products", tags=["catalogue"])
category_router = APIRouter(prefix="/categories", tags=["catalogue"])

# Type alias for the DB session dependency
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latest_prices_subquery() -> Subquery:
    """Build a subquery returning the latest price per product per store.

    Returns:
        A SQLAlchemy subquery with columns: product_id, store_id,
        max_recorded_at.
    """
    return (
        select(
            Price.product_id,
            Price.store_id,
            func.max(Price.recorded_at).label("max_recorded_at"),
        )
        .group_by(Price.product_id, Price.store_id)
        .subquery("latest")
    )


async def _price_summaries_for_product(
    db: AsyncSession,
    product_id: uuid.UUID,
) -> list[StorePriceSummary]:
    """Fetch current prices at every store for a single product.

    Args:
        db: Async database session.
        product_id: The product UUID.

    Returns:
        A list of StorePriceSummary objects, one per store.
    """
    latest = _latest_prices_subquery()
    stmt = (
        select(
            Price.store_id,
            Store.name.label("store_name"),
            Store.slug.label("store_slug"),
            Price.price,
            Price.currency,
            Price.unit,
            Price.pack_info,
            Price.recorded_at,
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Store, Store.id == Price.store_id)
        .where(Price.product_id == product_id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        StorePriceSummary(
            store_id=row.store_id,
            store_name=row.store_name,
            store_slug=row.store_slug,
            price=row.price,
            currency=row.currency,
            unit=row.unit,
            pack_info=row.pack_info,
            recorded_at=row.recorded_at,
        )
        for row in rows
    ]


async def _enrich_product_list(
    db: AsyncSession,
    products: list[Product],
) -> list[ProductListItem]:
    """Add price summary fields to a batch of products.

    For each product, calculates the lowest current price, distinct store
    count, and most recent price observation timestamp.

    Args:
        db: Async database session.
        products: ORM Product instances.

    Returns:
        A list of ProductListItem schemas with price summary data.
    """
    if not products:
        return []

    product_ids = [p.id for p in products]
    latest = _latest_prices_subquery()

    stmt = (
        select(
            Price.product_id,
            func.min(Price.price).label("lowest_price"),
            func.count(func.distinct(Price.store_id)).label("store_count"),
            func.max(Price.recorded_at).label("last_updated"),
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .where(Price.product_id.in_(product_ids))
        .group_by(Price.product_id)
    )
    rows = (await db.execute(stmt)).all()

    summary_map: dict[uuid.UUID, dict[str, Any]] = {
        row.product_id: {
            "lowest_price": row.lowest_price,
            "store_count": row.store_count,
            "last_updated": row.last_updated,
        }
        for row in rows
    }

    result: list[ProductListItem] = []
    for p in products:
        s = summary_map.get(p.id, {})
        result.append(
            ProductListItem(
                id=p.id,
                name=p.name,
                slug=p.slug,
                brand=p.brand,
                category_id=p.category_id,
                image_url=p.image_url,
                barcode=p.barcode,
                status=p.status.value if isinstance(p.status, ProductStatus) else p.status,
                lowest_price=s.get("lowest_price"),
                store_count=s.get("store_count", 0),
                last_updated=s.get("last_updated"),
            )
        )
    return result


def _collect_category_ids(
    category_id: uuid.UUID,
    children_map: dict[uuid.UUID | None, list[Category]],
) -> list[uuid.UUID]:
    """Recursively collect a category and all its descendant IDs.

    Args:
        category_id: The root category to start from.
        children_map: Mapping of parent_id -> list of child Category objects.

    Returns:
        A flat list of category UUIDs including the root.
    """
    ids = [category_id]
    for child in children_map.get(category_id, []):
        ids.extend(_collect_category_ids(child.id, children_map))
    return ids


def _build_tree(
    categories: list[Category],
) -> list[CategoryNode]:
    """Build a nested category tree from a flat list.

    Groups categories by parent_id and recursively nests children under
    their parent node.  Root nodes are those with parent_id = None.

    Args:
        categories: Flat list of Category ORM instances.

    Returns:
        A list of root-level CategoryNode objects with nested children.
    """
    children_map: dict[uuid.UUID | None, list[Category]] = {}
    for cat in categories:
        children_map.setdefault(cat.parent_id, []).append(cat)

    def _recurse(parent_id: uuid.UUID | None) -> list[CategoryNode]:
        nodes: list[CategoryNode] = []
        for cat in children_map.get(parent_id, []):
            nodes.append(
                CategoryNode(
                    id=cat.id,
                    name=cat.name,
                    slug=cat.slug,
                    parent_id=cat.parent_id,
                    children=_recurse(cat.id),
                )
            )
        return nodes

    return _recurse(None)


# ---------------------------------------------------------------------------
# Product endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedResponse[ProductListItem])
async def list_products(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    category_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    status: str | None = None,
) -> PaginatedResponse[ProductListItem]:
    """Return a paginated list of products with optional filters.

    Args:
        db: Async database session.
        limit: Maximum number of items per page (1-100, default 20).
        offset: Number of items to skip.
        category_id: Filter by category UUID.
        store_id: Filter by store UUID (products that have a price at
            the given store).
        status: Filter by product status. Defaults to 'active' only.

    Returns:
        PaginatedResponse containing ProductListItem objects.
    """
    effective_status = status or ProductStatus.ACTIVE.value

    # Base query
    stmt = select(Product).where(
        Product.status == effective_status,
    )
    count_stmt = select(func.count()).select_from(Product).where(
        Product.status == effective_status,
    )

    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
        count_stmt = count_stmt.where(Product.category_id == category_id)

    if store_id is not None:
        store_filter = select(Price.product_id).where(
            Price.store_id == store_id,
        ).distinct().subquery()
        stmt = stmt.where(Product.id.in_(select(store_filter)))
        count_stmt = count_stmt.where(Product.id.in_(select(store_filter)))

    total: int = (await db.execute(count_stmt)).scalar_one()
    products = list(
        (await db.execute(stmt.offset(offset).limit(limit).order_by(Product.name))).scalars().all()
    )

    items = await _enrich_product_list(db, products)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/search", response_model=PaginatedResponse[ProductListItem])
async def search_products(
    db: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ProductListItem]:
    """Search products by name and brand using full-text search.

    Uses PostgreSQL ``to_tsvector`` / ``plainto_tsquery`` for ranked
    full-text search.  If full-text search yields no results, falls back
    to a case-insensitive ``ILIKE`` match on the product name.

    Args:
        db: Async database session.
        q: Search query string.
        limit: Maximum items per page (1-100, default 20).
        offset: Number of items to skip.

    Returns:
        PaginatedResponse containing matching ProductListItem objects.
    """
    # Full-text search using tsvector
    ts_vector = func.to_tsvector(
        text("'bulgarian'"),
        Product.name + text("' '") + func.coalesce(Product.brand, text("''")),
    )
    ts_query = func.plainto_tsquery(text("'bulgarian'"), q)

    fts_stmt = (
        select(Product)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .where(ts_vector.bool_op("@@")(ts_query))
    )
    fts_count_stmt = (
        select(func.count())
        .select_from(Product)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .where(ts_vector.bool_op("@@")(ts_query))
    )

    total: int = (await db.execute(fts_count_stmt)).scalar_one()

    if total > 0:
        products = list(
            (await db.execute(
                fts_stmt.offset(offset).limit(limit).order_by(Product.name)
            )).scalars().all()
        )
    else:
        # Fallback: ILIKE on name
        like_pattern = f"%{q}%"
        ilike_stmt = (
            select(Product)
            .where(Product.status == ProductStatus.ACTIVE.value)
            .where(Product.name.ilike(like_pattern))
        )
        ilike_count_stmt = (
            select(func.count())
            .select_from(Product)
            .where(Product.status == ProductStatus.ACTIVE.value)
            .where(Product.name.ilike(like_pattern))
        )
        total = (await db.execute(ilike_count_stmt)).scalar_one()
        products = list(
            (await db.execute(
                ilike_stmt.offset(offset).limit(limit).order_by(Product.name)
            )).scalars().all()
        )

    items = await _enrich_product_list(db, products)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/compare", response_model=SearchCompareResponse)
async def search_compare(
    db: DbSession,
    q: Annotated[str, Query(min_length=1, max_length=200)],
) -> SearchCompareResponse:
    """Search for products and return the cheapest store price for each match.

    Uses the same full-text search logic as the catalogue search endpoint,
    returning up to 5 matching products each with their cheapest current
    store price.

    Args:
        db: Async database session.
        q: Search query string.

    Returns:
        SearchCompareResponse with top 5 matching products and cheapest prices.
    """
    # Full-text search (same logic as search_products)
    ts_vector = func.to_tsvector(
        text("'bulgarian'"),
        Product.name + text("' '") + func.coalesce(Product.brand, text("''")),
    )
    ts_query = func.plainto_tsquery(text("'bulgarian'"), q)

    fts_stmt = (
        select(Product)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .where(ts_vector.bool_op("@@")(ts_query))
        .limit(5)
        .order_by(Product.name)
    )
    products = list((await db.execute(fts_stmt)).scalars().all())

    # Fallback to ILIKE if FTS yields no results
    if not products:
        like_pattern = f"%{q}%"
        ilike_stmt = (
            select(Product)
            .where(Product.status == ProductStatus.ACTIVE.value)
            .where(Product.name.ilike(like_pattern))
            .limit(5)
            .order_by(Product.name)
        )
        products = list((await db.execute(ilike_stmt)).scalars().all())

    if not products:
        return SearchCompareResponse(query=q, results=[])

    product_ids = [p.id for p in products]
    latest = _latest_prices_subquery()

    # For each product, get cheapest current price + store info + store count
    cheapest_sub = (
        select(
            Price.product_id,
            func.min(Price.price).label("min_price"),
            func.count(func.distinct(Price.store_id)).label("store_count"),
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .where(Price.product_id.in_(product_ids))
        .group_by(Price.product_id)
        .subquery("cheapest")
    )

    # Join back to get the store that has the min price
    store_stmt = (
        select(
            Price.product_id,
            Store.name.label("store_name"),
            Store.slug.label("store_slug"),
            Price.price,
            Price.currency,
            cheapest_sub.c.store_count,
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Store, Store.id == Price.store_id)
        .join(
            cheapest_sub,
            (Price.product_id == cheapest_sub.c.product_id)
            & (Price.price == cheapest_sub.c.min_price),
        )
        .where(Price.product_id.in_(product_ids))
    )
    rows = (await db.execute(store_stmt)).all()

    # Deduplicate: keep first (cheapest) per product_id
    seen: set[uuid.UUID] = set()
    price_map: dict[uuid.UUID, Any] = {}
    for row in rows:
        if row.product_id not in seen:
            seen.add(row.product_id)
            price_map[row.product_id] = row

    results: list[SearchCompareItem] = []
    for p in products:
        row = price_map.get(p.id)  # type: ignore[assignment]
        if row is None:
            continue
        results.append(
            SearchCompareItem(
                product_id=p.id,
                product_name=p.name,
                product_slug=p.slug,
                brand=p.brand,
                cheapest_store_name=row.store_name,
                cheapest_store_slug=row.store_slug,
                cheapest_price=row.price,
                currency=row.currency,
                store_count=row.store_count,
            )
        )

    return SearchCompareResponse(query=q, results=results)


@router.get("/{product_id}", response_model=ProductDetail)
async def get_product(
    db: DbSession,
    product_id: uuid.UUID,
) -> ProductDetail:
    """Return full product detail with current prices at all stores.

    Args:
        db: Async database session.
        product_id: UUID of the product to retrieve.

    Returns:
        ProductDetail with per-store price breakdown.

    Raises:
        HTTPException: 404 if the product does not exist.
    """
    stmt = select(Product).where(Product.id == product_id)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    prices = await _price_summaries_for_product(db, product.id)
    lowest = min((p.price for p in prices), default=None)
    last_updated = max((p.recorded_at for p in prices), default=None)

    return ProductDetail(
        id=product.id,
        name=product.name,
        slug=product.slug,
        brand=product.brand,
        category_id=product.category_id,
        image_url=product.image_url,
        barcode=product.barcode,
        status=product.status.value if isinstance(product.status, ProductStatus) else product.status,
        lowest_price=lowest,
        store_count=len(prices),
        last_updated=last_updated,
        prices=prices,
    )


@router.get("/{product_id}/compare", response_model=ComparisonResponse)
async def compare_product_prices(
    db: DbSession,
    product_id: uuid.UUID,
) -> ComparisonResponse:
    """Compare the current price of a product across all stores that carry it.

    Returns per-store price data sorted cheapest first, with each entry
    showing the percentage difference from the lowest price.

    Args:
        db: Async database session.
        product_id: UUID of the product to compare.

    Returns:
        ComparisonResponse with per-store comparisons sorted by price.

    Raises:
        HTTPException: 404 if the product does not exist.
    """
    stmt = select(Product).where(Product.id == product_id)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    latest = _latest_prices_subquery()
    price_stmt = (
        select(
            Price.store_id,
            Store.name.label("store_name"),
            Store.slug.label("store_slug"),
            Store.logo_url.label("logo_url"),
            Price.price,
            Price.currency,
            Price.unit,
            Price.recorded_at,
            Price.source,
        )
        .join(
            latest,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Store, Store.id == Price.store_id)
        .where(Price.product_id == product_id)
        .order_by(Price.price.asc())
    )
    rows = (await db.execute(price_stmt)).all()

    if not rows:
        return ComparisonResponse(
            product_id=product.id,
            product_name=product.name,
            product_slug=product.slug,
            comparisons=[],
        )

    min_price = min(row.price for row in rows)
    comparisons: list[StoreComparison] = []
    for row in rows:
        diff_pct = round(float((row.price - min_price) / min_price * 100), 1) if min_price > 0 else 0.0
        comparisons.append(
            StoreComparison(
                store_id=row.store_id,
                store_name=row.store_name,
                store_slug=row.store_slug,
                logo_url=row.logo_url,
                price=row.price,
                currency=row.currency,
                unit=row.unit,
                last_scraped_at=row.recorded_at,
                source=row.source,
                price_diff_pct=diff_pct,
            )
        )

    return ComparisonResponse(
        product_id=product.id,
        product_name=product.name,
        product_slug=product.slug,
        comparisons=comparisons,
    )


# ---------------------------------------------------------------------------
# Category endpoints
# ---------------------------------------------------------------------------


@category_router.get("", response_model=list[CategoryNode])
async def list_categories(
    db: DbSession,
) -> list[CategoryNode]:
    """Return the full category tree as a nested structure.

    Loads all categories in a single query and builds the tree in Python.

    Args:
        db: Async database session.

    Returns:
        A list of root CategoryNode objects with nested children.
    """
    stmt = select(Category).order_by(Category.name)
    categories = list((await db.execute(stmt)).scalars().all())
    return _build_tree(categories)


@category_router.get(
    "/{category_id}/products",
    response_model=PaginatedResponse[ProductListItem],
)
async def list_category_products(
    db: DbSession,
    category_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ProductListItem]:
    """Return paginated products in a category, including subcategories.

    Collects all descendant category IDs and returns products belonging
    to any of them.

    Args:
        db: Async database session.
        category_id: UUID of the parent category.
        limit: Maximum items per page (1-100, default 20).
        offset: Number of items to skip.

    Returns:
        PaginatedResponse containing ProductListItem objects.

    Raises:
        HTTPException: 404 if the category does not exist.
    """
    # Verify category exists
    cat = (await db.execute(
        select(Category).where(Category.id == category_id)
    )).scalar_one_or_none()
    if cat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Load all categories to build child map
    all_cats = list(
        (await db.execute(select(Category))).scalars().all()
    )
    children_map: dict[uuid.UUID | None, list[Category]] = {}
    for c in all_cats:
        children_map.setdefault(c.parent_id, []).append(c)

    cat_ids = _collect_category_ids(category_id, children_map)

    stmt = (
        select(Product)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .where(Product.category_id.in_(cat_ids))
    )
    count_stmt = (
        select(func.count())
        .select_from(Product)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .where(Product.category_id.in_(cat_ids))
    )

    total: int = (await db.execute(count_stmt)).scalar_one()
    products = list(
        (await db.execute(
            stmt.offset(offset).limit(limit).order_by(Product.name)
        )).scalars().all()
    )

    items = await _enrich_product_list(db, products)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
