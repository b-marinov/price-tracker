"""Admin endpoints for product review workflow."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.config import get_settings
from app.database import get_db_session
from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.scrapers.tasks import run_all_scrapers, run_scraper

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Schemas ----------


class PendingProductOut(PydanticBaseModel):
    """Response schema for a product pending review."""

    id: uuid.UUID
    name: str
    brand: str | None
    barcode: str | None
    created_at: datetime
    matched_store_names: list[str]
    latest_price: float | None = None
    category: str | None = None
    discount_percent: int | None = None

    model_config = {"from_attributes": True}


class PaginatedPendingProducts(PydanticBaseModel):
    """Paginated response for pending products."""

    items: list[PendingProductOut]
    total: int
    page: int
    page_size: int


class ActiveProductOut(PydanticBaseModel):
    """Response schema for an active catalogue product."""

    id: uuid.UUID
    name: str
    brand: str | None
    barcode: str | None
    slug: str
    created_at: datetime
    matched_store_names: list[str]
    latest_price: float | None = None
    category: str | None = None
    discount_percent: int | None = None

    model_config = {"from_attributes": True}


class PaginatedActiveProducts(PydanticBaseModel):
    """Paginated response for active catalogue products."""

    items: list[ActiveProductOut]
    total: int
    page: int
    page_size: int


class ProductActionOut(PydanticBaseModel):
    """Response schema for approve/reject actions."""

    id: uuid.UUID
    status: str
    message: str


class ProductUpdateIn(PydanticBaseModel):
    """Request schema for partial product updates."""

    name: str | None = None
    brand: str | None = None
    barcode: str | None = None


# ---------- Auth dependency ----------


async def verify_admin_key(
    x_admin_key: Annotated[str, Header()],
) -> str:
    """Validate the admin API key from the request header.

    Args:
        x_admin_key: The API key sent via ``X-Admin-Key`` header.

    Returns:
        The validated key string.

    Raises:
        HTTPException: 403 if the key is missing or invalid.
    """
    settings = get_settings()
    if x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    return x_admin_key


# ---------- Endpoints ----------


@router.get(
    "/products/pending",
    response_model=PaginatedPendingProducts,
)
async def list_pending_products(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedPendingProducts:
    """Return a paginated list of products awaiting review.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).
        page: Page number (1-indexed).
        page_size: Number of items per page.

    Returns:
        Paginated list of pending products with matched store names.
    """
    # Total count
    count_result = await db.execute(
        select(func.count(Product.id)).where(
            Product.status == ProductStatus.PENDING_REVIEW
        )
    )
    total: int = count_result.scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Product)
        .where(Product.status == ProductStatus.PENDING_REVIEW)
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    products: list[Product] = list(result.scalars().all())

    # For each product, find store names and the latest price row
    items: list[PendingProductOut] = []
    for product in products:
        store_result = await db.execute(
            select(Store.name)
            .join(Price, Price.store_id == Store.id)
            .where(Price.product_id == product.id)
            .distinct()
        )
        store_names: list[str] = list(store_result.scalars().all())

        latest_price_result = await db.execute(
            select(Price.price, Price.category, Price.discount_percent)
            .where(Price.product_id == product.id)
            .order_by(Price.recorded_at.desc())
            .limit(1)
        )
        latest_price_row = latest_price_result.first()

        items.append(
            PendingProductOut(
                id=product.id,
                name=product.name,
                brand=product.brand,
                barcode=product.barcode,
                created_at=product.created_at,
                matched_store_names=store_names,
                latest_price=float(latest_price_row.price) if latest_price_row else None,
                category=latest_price_row.category if latest_price_row else None,
                discount_percent=latest_price_row.discount_percent if latest_price_row else None,
            )
        )

    return PaginatedPendingProducts(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/products/{product_id}",
    response_model=ProductActionOut,
)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdateIn,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProductActionOut:
    """Partially update mutable fields of a product.

    Only the fields present and non-``None`` in the request body are applied.
    Fields omitted or explicitly ``null`` are left unchanged.

    Args:
        product_id: UUID of the product to update.
        body: Partial update payload (``name``, ``brand``, ``barcode``).
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation with the product id, current status, and update message.

    Raises:
        HTTPException: 404 if the product is not found.
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalars().first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)

    return ProductActionOut(
        id=product.id,
        status=product.status.value if isinstance(product.status, ProductStatus) else product.status,
        message="Product updated",
    )


@router.patch(
    "/products/{product_id}/approve",
    response_model=ProductActionOut,
)
async def approve_product(
    product_id: uuid.UUID,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProductActionOut:
    """Approve a pending product, setting its status to active.

    Args:
        product_id: UUID of the product to approve.
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation with updated product id and status.

    Raises:
        HTTPException: 404 if product not found.
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalars().first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product.status = ProductStatus.ACTIVE
    await db.commit()
    await db.refresh(product)

    return ProductActionOut(
        id=product.id,
        status=product.status.value if isinstance(product.status, ProductStatus) else product.status,
        message="Product approved",
    )


@router.patch(
    "/products/{product_id}/reject",
    response_model=ProductActionOut,
)
async def reject_product(
    product_id: uuid.UUID,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProductActionOut:
    """Reject and delete a pending product.

    Only products with ``status=pending_review`` can be rejected.
    Attempting to reject an active product returns 400.

    Args:
        product_id: UUID of the product to reject.
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation with the deleted product id.

    Raises:
        HTTPException: 404 if product not found, 400 if product is active.
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalars().first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    current_status = (
        product.status.value
        if isinstance(product.status, ProductStatus)
        else product.status
    )
    if current_status != ProductStatus.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=400,
            detail="Cannot reject a product that is not pending review",
        )

    product_id_copy = product.id
    await db.delete(product)
    await db.commit()

    return ProductActionOut(
        id=product_id_copy,
        status="rejected",
        message="Product rejected and deleted",
    )


# ---------- Catalogue endpoints ----------


@router.get(
    "/products",
    response_model=PaginatedActiveProducts,
)
async def list_active_products(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> PaginatedActiveProducts:
    """Return a paginated list of active catalogue products.

    Optionally filters by a search query matched against product name and brand.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).
        page: Page number (1-indexed).
        page_size: Number of items per page.
        q: Optional search string matched against name / brand.

    Returns:
        Paginated list of active products.
    """
    from sqlalchemy import or_

    base_filter = Product.status == ProductStatus.ACTIVE
    if q:
        search = f"%{q}%"
        base_filter = base_filter & (
            or_(
                Product.name.ilike(search),
                Product.brand.ilike(search),
            )
        )

    count_result = await db.execute(
        select(func.count(Product.id)).where(base_filter)
    )
    total: int = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Product)
        .where(base_filter)
        .order_by(Product.name.asc())
        .offset(offset)
        .limit(page_size)
    )
    products: list[Product] = list(result.scalars().all())

    items: list[ActiveProductOut] = []
    for product in products:
        store_result = await db.execute(
            select(Store.name)
            .join(Price, Price.store_id == Store.id)
            .where(Price.product_id == product.id)
            .distinct()
        )
        store_names: list[str] = list(store_result.scalars().all())

        latest_price_result = await db.execute(
            select(Price.price, Price.category, Price.discount_percent)
            .where(Price.product_id == product.id)
            .order_by(Price.recorded_at.desc())
            .limit(1)
        )
        latest_price_row = latest_price_result.first()

        items.append(
            ActiveProductOut(
                id=product.id,
                name=product.name,
                brand=product.brand,
                barcode=product.barcode,
                slug=product.slug,
                created_at=product.created_at,
                matched_store_names=store_names,
                latest_price=float(latest_price_row.price) if latest_price_row else None,
                category=latest_price_row.category if latest_price_row else None,
                discount_percent=latest_price_row.discount_percent if latest_price_row else None,
            )
        )

    return PaginatedActiveProducts(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/products/{product_id}",
    response_model=ProductActionOut,
)
async def delete_product(
    product_id: uuid.UUID,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProductActionOut:
    """Permanently delete a product and all its price history.

    Args:
        product_id: UUID of the product to delete.
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation with the deleted product id.

    Raises:
        HTTPException: 404 if product not found.
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalars().first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product_id_copy = product.id
    await db.delete(product)
    await db.commit()

    return ProductActionOut(
        id=product_id_copy,
        status="deleted",
        message="Product deleted",
    )


# ---------- Scraper endpoints ----------


class ScraperRunOut(PydanticBaseModel):
    """Response schema for scraper dispatch."""

    dispatched: list[str]
    message: str


@router.post("/scrapers/run", response_model=ScraperRunOut)
async def trigger_all_scrapers(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ScraperRunOut:
    """Dispatch scraper tasks for all active stores.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        List of store slugs whose scrapers were dispatched.
    """
    result = await db.execute(
        select(Store.slug).where(Store.active.is_(True))
    )
    slugs: list[str] = list(result.scalars().all())

    for slug in slugs:
        run_scraper.delay(slug)

    return ScraperRunOut(
        dispatched=slugs,
        message=f"Dispatched scrapers for {len(slugs)} store(s)",
    )


@router.post("/scrapers/run/{store_slug}", response_model=ScraperRunOut)
async def trigger_store_scraper(
    store_slug: str,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ScraperRunOut:
    """Dispatch a scraper task for a single store.

    Args:
        store_slug: Slug identifier of the store (e.g. ``kaufland``).
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation with the dispatched store slug.

    Raises:
        HTTPException: 404 if no active store with that slug exists.
    """
    result = await db.execute(
        select(Store).where(Store.slug == store_slug, Store.active.is_(True))
    )
    store = result.scalars().first()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found or inactive")

    run_scraper.delay(store_slug)

    return ScraperRunOut(
        dispatched=[store_slug],
        message=f"Dispatched scraper for {store_slug}",
    )
