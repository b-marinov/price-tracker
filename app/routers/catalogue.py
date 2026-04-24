"""Product catalogue API endpoints.

Provides browsing, searching, and category navigation for the product
catalogue.  The primary list endpoint aggregates products by catalog
name (e.g. a single "Бира" entry covering every brand/pack/store), so
the UI shows one entry per conceptual product.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
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
    ProductFamilyDetail,
    ProductFamilyListItem,
    ProductFamilyVariant,
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
            Price.pack_type,
            Price.generic_pack,
            Price.brand,
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
            pack_type=row.pack_type,
            generic_pack=row.generic_pack,
            brand=row.brand,
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
                pack_info=p.pack_info,
                additional_info=p.additional_info,
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
# Product family helpers (aggregate by catalog name)
# ---------------------------------------------------------------------------

# Bulgarian Cyrillic → ASCII transliteration for URL slugs.  Based on the
# official Bulgarian government streamlined system.
_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sht", "ъ": "a",
    "ь": "y", "ю": "yu", "я": "ya",
}


def _name_to_slug(name: str) -> str:
    """Convert a product name to a URL-safe ASCII slug.

    Transliterates Cyrillic to Latin and replaces all non-alphanumeric
    characters with hyphens.  The result is lowercase.
    """
    out: list[str] = []
    for ch in name.lower():
        if ch in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "product"


# Regex for "<number> <unit>" pack-size strings, allowing a multi-pack prefix
# like "6 x " or "6x".  Handles both Bulgarian and Latin-script unit tokens.
_PACK_RE = re.compile(
    r"(?:(?P<count>\d+(?:[.,]\d+)?)\s*[xх×]\s*)?"
    r"(?P<size>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>мл|ml|л|l|г|гр|g|кг|kg|бр)",
    re.IGNORECASE,
)

_UNIT_TO_BASE: dict[str, tuple[float, str]] = {
    "мл": (0.001, "л"), "ml": (0.001, "л"),
    "л":  (1.0,   "л"), "l":  (1.0,   "л"),
    "г":  (0.001, "кг"), "гр": (0.001, "кг"), "g":  (0.001, "кг"),
    "кг": (1.0,   "кг"), "kg": (1.0,   "кг"),
    "бр": (1.0,   "бр"),
}


def _parse_pack_to_base(pack: str | None) -> tuple[float, str] | None:
    """Parse a pack string into (total_size_in_base_unit, base_unit).

    Base units are "л" for volume, "кг" for mass, "бр" for count-only.
    Multi-pack prefixes like ``"6 x 0.5 л"`` are multiplied through.

    Returns None when the pack string cannot be parsed.
    """
    if not pack:
        return None
    m = _PACK_RE.search(pack)
    if not m:
        return None
    size = float(m.group("size").replace(",", "."))
    count = float(m.group("count").replace(",", ".")) if m.group("count") else 1.0
    mult, base = _UNIT_TO_BASE[m.group("unit").lower()]
    return size * count * mult, base


def _compute_per_unit(
    price: Decimal | None,
    pack: str | None,
) -> tuple[Decimal | None, str | None]:
    """Compute price per base unit (€/л or €/кг or €/бр).

    Returns (price_per_unit, "€/<base_unit>") or (None, None) when the
    pack cannot be parsed or its total size is zero.
    """
    if price is None:
        return None, None
    parsed = _parse_pack_to_base(pack)
    if parsed is None:
        return None, None
    size, base = parsed
    if size <= 0:
        return None, None
    return (price / Decimal(str(size))).quantize(Decimal("0.01")), base


# ---------------------------------------------------------------------------
# Product endpoints
# ---------------------------------------------------------------------------


async def _paginated_families_where(
    db: AsyncSession,
    base_where: list[Any],
    limit: int,
    offset: int,
) -> PaginatedResponse[ProductFamilyListItem]:
    """Aggregate products by catalog name and return a paginated page.

    Args:
        db: Async database session.
        base_where: SQLAlchemy WHERE-clause expressions applied to Product.
        limit: Items per page.
        offset: Number of items to skip.
    """
    latest = _latest_prices_subquery()

    count_stmt = (
        select(func.count(func.distinct(Product.name)))
        .where(*base_where)
    )
    total: int = (await db.execute(count_stmt)).scalar_one()

    names_stmt = (
        select(Product.name)
        .where(*base_where)
        .group_by(Product.name)
        .order_by(Product.name)
        .offset(offset)
        .limit(limit)
    )
    page_names: list[str] = [r[0] for r in (await db.execute(names_stmt)).all()]
    if not page_names:
        return PaginatedResponse(items=[], total=total, limit=limit, offset=offset)

    # Fetch every variant+latest-price for the page's names in one query
    variant_stmt = (
        select(
            Product.id.label("product_id"),
            Product.name,
            Product.brand,
            Product.pack_info,
            Product.category_id,
            Product.image_url.label("product_image_url"),
            Price.price,
            Price.store_id,
            Price.image_url.label("price_image_url"),
            Price.recorded_at,
        )
        .join(
            latest,
            (Product.id == latest.c.product_id),
        )
        .join(
            Price,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .where(
            Product.name.in_(page_names),
            Product.status == ProductStatus.ACTIVE.value,
        )
    )
    rows = (await db.execute(variant_stmt)).all()

    # Resolve category names in one query
    cat_ids: set[uuid.UUID] = {r.category_id for r in rows if r.category_id is not None}
    cat_name_map: dict[uuid.UUID, str] = {}
    if cat_ids:
        cat_rows = (
            await db.execute(select(Category.id, Category.name).where(Category.id.in_(cat_ids)))
        ).all()
        cat_name_map = {r.id: r.name for r in cat_rows}

    # Aggregate per-name in Python (small page size keeps this trivial)
    by_name: dict[str, dict[str, Any]] = {n: {
        "brands": set(),
        "packs": set(),
        "stores": set(),
        "variants": 0,
        "min_price": None,
        "min_ppu": None,
        "ppu_basis": None,
        "image": None,
        "category_id": None,
        "last_updated": None,
    } for n in page_names}

    for r in rows:
        slot = by_name[r.name]
        if r.brand:
            slot["brands"].add(r.brand.strip().lower())
        if r.pack_info:
            slot["packs"].add(r.pack_info.strip().lower())
        slot["stores"].add(r.store_id)
        slot["variants"] += 1
        if slot["min_price"] is None or r.price < slot["min_price"]:
            slot["min_price"] = r.price
        ppu, basis = _compute_per_unit(r.price, r.pack_info)
        if ppu is not None and (slot["min_ppu"] is None or ppu < slot["min_ppu"]):
            slot["min_ppu"] = ppu
            slot["ppu_basis"] = basis
        if slot["image"] is None:
            slot["image"] = r.price_image_url or r.product_image_url
        if slot["category_id"] is None and r.category_id is not None:
            slot["category_id"] = r.category_id
        if slot["last_updated"] is None or r.recorded_at > slot["last_updated"]:
            slot["last_updated"] = r.recorded_at

    items: list[ProductFamilyListItem] = []
    for n in page_names:
        s = by_name[n]
        items.append(
            ProductFamilyListItem(
                name=n,
                name_slug=_name_to_slug(n),
                category_id=s["category_id"],
                category_name=cat_name_map.get(s["category_id"]) if s["category_id"] else None,
                image_url=s["image"],
                brand_count=len(s["brands"]),
                pack_count=len(s["packs"]),
                store_count=len(s["stores"]),
                variant_count=s["variants"],
                lowest_price=s["min_price"],
                lowest_price_per_unit=s["min_ppu"],
                per_unit_basis=s["ppu_basis"],
                last_updated=s["last_updated"],
            )
        )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("", response_model=PaginatedResponse[ProductFamilyListItem])
async def list_products(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    category_id: uuid.UUID | None = None,
    store_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> PaginatedResponse[ProductFamilyListItem]:
    """Return a paginated list of product families aggregated by catalog name.

    One entry per distinct ``product.name`` (e.g. a single "Бира" entry
    covering every brand / pack / store).  The UI shows one card per
    entry and users drill into ``/products/by-name/{slug}`` to see the
    full brand × pack × store breakdown.

    Args:
        q: Optional case-insensitive substring filter on the product name.
    """
    base_where: list[Any] = [Product.status == ProductStatus.ACTIVE.value]
    if category_id is not None:
        base_where.append(Product.category_id == category_id)
    if store_id is not None:
        store_filter = (
            select(Price.product_id)
            .where(Price.store_id == store_id)
            .distinct()
            .subquery()
        )
        base_where.append(Product.id.in_(select(store_filter)))
    if q:
        base_where.append(Product.name.ilike(f"%{q.strip()}%"))
    return await _paginated_families_where(db, base_where, limit, offset)


@router.get("/by-name/{name_slug}", response_model=ProductFamilyDetail)
async def get_product_family(
    db: DbSession,
    name_slug: str,
) -> ProductFamilyDetail:
    """Return every (brand × pack × store) variant for a catalog product name.

    Args:
        db: Async database session.
        name_slug: The URL-safe slug produced by :func:`_name_to_slug`.

    Returns:
        Full ProductFamilyDetail with one variant entry per (product, store).

    Raises:
        HTTPException: 404 if no products match the slug.
    """
    # Resolve slug → candidate names by computing slug for every distinct name.
    distinct_names_stmt = (
        select(Product.name)
        .where(Product.status == ProductStatus.ACTIVE.value)
        .group_by(Product.name)
    )
    all_names = [r[0] for r in (await db.execute(distinct_names_stmt)).all()]
    matching_names = [n for n in all_names if _name_to_slug(n) == name_slug]
    if not matching_names:
        raise HTTPException(status_code=404, detail="Продуктът не е намерен")

    name = matching_names[0]
    latest = _latest_prices_subquery()

    variant_stmt = (
        select(
            Product.id.label("product_id"),
            Product.brand,
            Product.pack_info,
            Product.generic_pack,
            Product.pack_type,
            Product.category_id,
            Product.image_url.label("product_image_url"),
            Price.store_id,
            Store.name.label("store_name"),
            Store.slug.label("store_slug"),
            Price.price,
            Price.currency,
            Price.unit,
            Price.original_price,
            Price.discount_percent,
            Price.image_url.label("price_image_url"),
            Price.recorded_at,
        )
        .join(
            latest,
            Product.id == latest.c.product_id,
        )
        .join(
            Price,
            (Price.product_id == latest.c.product_id)
            & (Price.store_id == latest.c.store_id)
            & (Price.recorded_at == latest.c.max_recorded_at),
        )
        .join(Store, Store.id == Price.store_id)
        .where(
            Product.name == name,
            Product.status == ProductStatus.ACTIVE.value,
        )
        .order_by(Price.price)
    )
    rows = (await db.execute(variant_stmt)).all()

    variants: list[ProductFamilyVariant] = []
    brands: set[str] = set()
    packs: set[str] = set()
    stores: set[uuid.UUID] = set()
    min_price: Decimal | None = None
    min_ppu: Decimal | None = None
    ppu_basis: str | None = None
    any_image: str | None = None
    any_category: uuid.UUID | None = None
    for r in rows:
        if r.brand:
            brands.add(r.brand.strip())
        if r.pack_info:
            packs.add(r.pack_info.strip().lower())
        stores.add(r.store_id)
        if min_price is None or r.price < min_price:
            min_price = r.price
        ppu, basis = _compute_per_unit(r.price, r.pack_info)
        if ppu is not None and (min_ppu is None or ppu < min_ppu):
            min_ppu = ppu
            ppu_basis = basis
        img = r.price_image_url or r.product_image_url
        if img and any_image is None:
            any_image = img
        if any_category is None and r.category_id is not None:
            any_category = r.category_id
        variants.append(
            ProductFamilyVariant(
                product_id=r.product_id,
                brand=r.brand,
                pack_info=r.pack_info,
                generic_pack=r.generic_pack,
                pack_type=r.pack_type,
                store_id=r.store_id,
                store_name=r.store_name,
                store_slug=r.store_slug,
                price=r.price,
                price_per_unit=ppu,
                per_unit_basis=basis,
                currency=r.currency or "EUR",
                unit=r.unit,
                original_price=r.original_price,
                discount_percent=float(r.discount_percent) if r.discount_percent is not None else None,
                image_url=img,
                recorded_at=r.recorded_at,
            )
        )

    category_name: str | None = None
    if any_category is not None:
        cat = (
            await db.execute(select(Category.name).where(Category.id == any_category))
        ).scalar_one_or_none()
        category_name = cat

    return ProductFamilyDetail(
        name=name,
        name_slug=name_slug,
        category_id=any_category,
        category_name=category_name,
        image_url=any_image,
        brand_count=len(brands),
        pack_count=len(packs),
        store_count=len(stores),
        variant_count=len(variants),
        lowest_price=min_price,
        lowest_price_per_unit=min_ppu,
        per_unit_basis=ppu_basis,
        brands=sorted(brands),
        variants=variants,
    )


async def _enrich_product_detail(product: Product) -> ProductDetail:
    """Enrich a Product with full pack info and return as ProductDetail.

    Args:
        product: A Product ORM instance.

    Returns:
        ProductDetail schema with price variants.
    """
    prices = await _price_summaries_for_product(db, product.id)

    # Build full pack_info strings combining generic_pack + pack_type
    return ProductDetail(
        id=product.id,
        name=product.name,
        slug=product.slug,
        brand=product.brand,
        generic_pack=product.generic_pack,
        pack_type=product.pack_type,
        pack_info=product.pack_info,  # Computed for backward compatibility
        additional_info=product.additional_info,
        category_id=product.category_id,
        image_url=product.image_url,
        barcode=product.barcode,
        status=product.status.value if isinstance(product.status, ProductStatus) else product.status,
        lowest_price=min((p.price for p in prices), default=None),
        store_count=len(prices),
        last_updated=max((p.recorded_at for p in prices), default=None),
        prices=prices,
    )


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
        generic_pack=product.generic_pack,
        pack_type=product.pack_type,
        pack_info=product.pack_info,  # Computed for backward compatibility
        additional_info=product.additional_info,
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
    response_model=PaginatedResponse[ProductFamilyListItem],
)
async def list_category_products(
    db: DbSession,
    category_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse[ProductFamilyListItem]:
    """Return paginated product families in a category + descendants.

    Returns the same catalog-name aggregation as ``GET /products``,
    scoped to the category tree rooted at ``category_id``.

    Raises:
        HTTPException: 404 if the category does not exist.
    """
    cat = (await db.execute(
        select(Category).where(Category.id == category_id)
    )).scalar_one_or_none()
    if cat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    all_cats = list((await db.execute(select(Category))).scalars().all())
    children_map: dict[uuid.UUID | None, list[Category]] = {}
    for c in all_cats:
        children_map.setdefault(c.parent_id, []).append(c)
    cat_ids = _collect_category_ids(category_id, children_map)

    return await _paginated_families_where(
        db,
        [
            Product.status == ProductStatus.ACTIVE.value,
            Product.category_id.in_(cat_ids),
        ],
        limit,
        offset,
    )
