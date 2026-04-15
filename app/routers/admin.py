"""Admin endpoints for product review workflow."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db_session
from app.models.price import Price
from app.models.product import Product, ProductStatus
from app.models.scrape_run import ScrapeRun, ScrapeStatus
from app.models.store import Store
from app.scrapers.tasks import run_scraper

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


class BatchDeleteIn(PydanticBaseModel):
    """Request schema for batch product deletion."""

    ids: list[uuid.UUID]


class BatchDeleteOut(PydanticBaseModel):
    """Response schema for batch product deletion."""

    deleted: int
    not_found: list[uuid.UUID]


class QueueStatusOut(PydanticBaseModel):
    """Queue depth and active task info."""
    pending: int
    active: list[str]    # store slugs currently being processed (status=running)
    queued: list[str]    # store slugs waiting in the Celery queue (not yet started)


class QueueClearOut(PydanticBaseModel):
    """Result of clearing the queue."""
    cleared: int


class LogEntryOut(PydanticBaseModel):
    """A single scraper log entry."""
    ts: str
    store: str
    level: str
    msg: str


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


@router.delete(
    "/products",
    response_model=BatchDeleteOut,
)
async def batch_delete_products(
    body: BatchDeleteIn,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BatchDeleteOut:
    """Permanently delete multiple products and all their price history.

    Args:
        body: List of product UUIDs to delete.
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Count of deleted products and list of IDs not found.
    """
    if not body.ids:
        return BatchDeleteOut(deleted=0, not_found=[])

    result = await db.execute(
        select(Product).where(Product.id.in_(body.ids))
    )
    found = result.scalars().all()
    found_ids = {p.id for p in found}
    not_found = [pid for pid in body.ids if pid not in found_ids]

    for product in found:
        await db.delete(product)
    await db.commit()

    return BatchDeleteOut(deleted=len(found), not_found=not_found)


# ---------- Scraper helpers ----------


def _scrape_run_has_alert(run: ScrapeRun) -> bool:
    """Return True when a scrape run deserves an operator alert.

    A run triggers an alert when it either failed outright or completed
    but found zero items (indicating a silent scraper failure).

    Args:
        run: The :class:`~app.models.scrape_run.ScrapeRun` to inspect.

    Returns:
        ``True`` if the run warrants an alert, ``False`` otherwise.
    """
    status_val = run.status.value if isinstance(run.status, ScrapeStatus) else run.status
    if status_val == ScrapeStatus.CANCELLED.value:
        return False
    if status_val == ScrapeStatus.FAILED.value:
        return True
    return status_val == ScrapeStatus.COMPLETED.value and run.items_found == 0


# ---------- Scraper endpoints ----------


class ScraperRunOut(PydanticBaseModel):
    """Response schema for scraper dispatch."""

    dispatched: list[str]
    message: str


class ScraperCancelOut(PydanticBaseModel):
    """Response schema for scraper cancel request."""

    store_slug: str
    message: str


class ScrapeRunStatusOut(PydanticBaseModel):
    """Status of the most recent scrape run for a store."""

    store_slug: str
    status: str          # "idle" | "running" | "completed" | "failed" | "cancelled"
    items_found: int | None
    error_msg: str | None
    started_at: datetime | None
    finished_at: datetime | None
    alert: bool = False  # True when status=failed OR completed with items_found=0


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


@router.delete("/scrapers/run/{store_slug}", response_model=ScraperCancelOut)
async def cancel_store_scraper(
    store_slug: str,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ScraperCancelOut:
    """Request cancellation of the running scraper for a store.

    Sets a Redis cancel flag that the scraper checks between pages/scrolls.
    The task will stop at the next checkpoint and mark the run as cancelled.
    Pending (queued but not started) tasks for this store are also revoked.

    Args:
        store_slug: Slug identifier of the store (e.g. ``kaufland``).
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Confirmation that the cancel flag was set.

    Raises:
        HTTPException: 404 if no store with that slug exists.
    """
    import redis as _redis_lib
    from app.config import get_settings
    from app.scrapers.cancel import request_cancel

    store_result = await db.execute(
        select(Store).where(Store.slug == store_slug)
    )
    store = store_result.scalars().first()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    # Look up the running task_id to attempt Celery revocation
    run_result = await db.execute(
        select(ScrapeRun)
        .where(
            ScrapeRun.store_id == store.id,
            ScrapeRun.status == ScrapeStatus.RUNNING,
        )
        .order_by(ScrapeRun.started_at.desc())
        .limit(1)
    )
    run = run_result.scalars().first()

    settings = get_settings()
    redis_client = _redis_lib.from_url(settings.REDIS_URL)
    try:
        # Set the soft cancel flag (scraper checks this between pages)
        request_cancel(redis_client, store_slug)

        # Also hard-revoke the Celery task if we have its ID
        if run and run.task_id:
            from app.scrapers.celery_app import celery_app
            celery_app.control.revoke(run.task_id, terminate=False)
    finally:
        redis_client.close()

    # Remove any pending (not-yet-started) messages for this store from the Celery queue
    import redis.asyncio as aioredis
    r_async = aioredis.from_url(settings.REDIS_URL)
    try:
        raw_messages = await r_async.lrange("celery", 0, 199)
        for raw in raw_messages:
            slug = _extract_slug_from_celery_message(raw)
            if slug == store_slug:
                await r_async.lrem("celery", 0, raw)
    finally:
        await r_async.aclose()

    return ScraperCancelOut(
        store_slug=store_slug,
        message=f"Cancel requested for {store_slug!r}. Scraper will stop at next checkpoint.",
    )


@router.get("/scrapers/status", response_model=list[ScrapeRunStatusOut])
async def get_all_scraper_statuses(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ScrapeRunStatusOut]:
    """Return the most recent scrape run status for every active store.

    Stores that have never been scraped appear with status ``"idle"`` and all
    other fields set to ``None``.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        List of :class:`ScrapeRunStatusOut`, one entry per active store.
    """
    from sqlalchemy import and_

    stores_result = await db.execute(
        select(Store).where(Store.active.is_(True))
    )
    stores: list[Store] = list(stores_result.scalars().all())

    # Fetch the latest run for each store in one query using a subquery for
    # the maximum started_at per store, then join back to get the full row.
    subq = (
        select(
            ScrapeRun.store_id,
            func.max(ScrapeRun.started_at).label("max_started_at"),
        )
        .group_by(ScrapeRun.store_id)
        .subquery()
    )

    runs_result = await db.execute(
        select(ScrapeRun).join(
            subq,
            and_(
                ScrapeRun.store_id == subq.c.store_id,
                ScrapeRun.started_at == subq.c.max_started_at,
            ),
        )
    )
    runs: list[ScrapeRun] = list(runs_result.scalars().all())
    runs_by_store_id = {run.store_id: run for run in runs}

    statuses: list[ScrapeRunStatusOut] = []
    for store in stores:
        run = runs_by_store_id.get(store.id)
        if run is None:
            statuses.append(
                ScrapeRunStatusOut(
                    store_slug=store.slug,
                    status="idle",
                    items_found=None,
                    error_msg=None,
                    started_at=None,
                    finished_at=None,
                )
            )
        else:
            statuses.append(
                ScrapeRunStatusOut(
                    store_slug=store.slug,
                    status=run.status.value if isinstance(run.status, ScrapeStatus) else run.status,
                    items_found=run.items_found,
                    error_msg=run.error_msg,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    alert=_scrape_run_has_alert(run),
                )
            )

    return statuses


@router.get("/scrapers/status/{store_slug}", response_model=ScrapeRunStatusOut)
async def get_scraper_status(
    store_slug: str,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ScrapeRunStatusOut:
    """Return the most recent scrape run status for a single store.

    If the store has never been scraped, returns status ``"idle"`` with all
    timestamp and count fields set to ``None``.

    Args:
        store_slug: Slug identifier of the store (e.g. ``kaufland``).
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        :class:`ScrapeRunStatusOut` with the latest run details, or an idle
        record when no run exists yet.

    Raises:
        HTTPException: 404 if no store with that slug exists.
    """
    store_result = await db.execute(
        select(Store).where(Store.slug == store_slug)
    )
    store = store_result.scalars().first()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    run_result = await db.execute(
        select(ScrapeRun)
        .where(ScrapeRun.store_id == store.id)
        .order_by(ScrapeRun.started_at.desc())
        .limit(1)
    )
    run = run_result.scalars().first()

    if run is None:
        return ScrapeRunStatusOut(
            store_slug=store_slug,
            status="idle",
            items_found=None,
            error_msg=None,
            started_at=None,
            finished_at=None,
        )

    return ScrapeRunStatusOut(
        store_slug=store_slug,
        status=run.status.value if isinstance(run.status, ScrapeStatus) else run.status,
        items_found=run.items_found,
        error_msg=run.error_msg,
        started_at=run.started_at,
        finished_at=run.finished_at,
        alert=_scrape_run_has_alert(run),
    )


@router.get("/scrapers/alerts", response_model=list[ScrapeRunStatusOut])
async def get_scraper_alerts(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ScrapeRunStatusOut]:
    """Return scrape runs that need operator attention.

    A run is included when its most recent completion either:

    * has ``status=failed``, or
    * has ``status=completed`` but ``items_found=0`` (silent scraper failure).

    Stores that have never been scraped are excluded.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        List of :class:`ScrapeRunStatusOut` entries where ``alert=True``.
        Empty list means all scrapers are healthy.
    """
    from sqlalchemy import and_

    stores_result = await db.execute(
        select(Store).where(Store.active.is_(True))
    )
    stores: list[Store] = list(stores_result.scalars().all())

    subq = (
        select(
            ScrapeRun.store_id,
            func.max(ScrapeRun.started_at).label("max_started_at"),
        )
        .group_by(ScrapeRun.store_id)
        .subquery()
    )

    runs_result = await db.execute(
        select(ScrapeRun).join(
            subq,
            and_(
                ScrapeRun.store_id == subq.c.store_id,
                ScrapeRun.started_at == subq.c.max_started_at,
            ),
        )
    )
    runs: list[ScrapeRun] = list(runs_result.scalars().all())
    runs_by_store_id = {run.store_id: run for run in runs}

    alerts: list[ScrapeRunStatusOut] = []
    for store in stores:
        run = runs_by_store_id.get(store.id)
        if run is None or not _scrape_run_has_alert(run):
            continue
        alerts.append(
            ScrapeRunStatusOut(
                store_slug=store.slug,
                status=run.status.value if isinstance(run.status, ScrapeStatus) else run.status,
                items_found=run.items_found,
                error_msg=run.error_msg,
                started_at=run.started_at,
                finished_at=run.finished_at,
                alert=True,
            )
        )

    return alerts


# ---------- Store management endpoints ----------


class StoreBrochureUrlIn(PydanticBaseModel):
    """Request body for setting a store's brochure_url."""

    brochure_url: str


class StoreBrochureUrlOut(PydanticBaseModel):
    """Response after updating a store's brochure_url."""

    store_slug: str
    brochure_url: str
    message: str


@router.patch(
    "/stores/{store_slug}/brochure-url",
    response_model=StoreBrochureUrlOut,
)
async def set_store_brochure_url(
    store_slug: str,
    body: StoreBrochureUrlIn,
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    tos_confirmed: bool = False,
) -> StoreBrochureUrlOut:
    """Set or update the brochure_url for a store.

    Before calling this endpoint you **must** complete the store onboarding
    checklist in ``CONTRIBUTING.md`` (robots.txt review, ToS review,
    stakeholder approval).  Pass ``tos_confirmed=true`` as a query parameter
    to confirm you have done so.

    Args:
        store_slug: Slug identifier of the store to update.
        body: JSON body containing the new ``brochure_url``.
        _key: Validated admin API key (injected).
        db: Async database session (injected).
        tos_confirmed: Must be ``true``; caller declares the onboarding
            checklist (robots.txt, ToS, Boris sign-off) has been completed.

    Returns:
        :class:`StoreBrochureUrlOut` with the updated URL.

    Raises:
        HTTPException: 400 if ``tos_confirmed`` is not ``true``.
        HTTPException: 404 if no store with that slug exists.
    """
    if not tos_confirmed:
        raise HTTPException(
            status_code=400,
            detail=(
                "tos_confirmed=true is required. "
                "Complete the store onboarding checklist in CONTRIBUTING.md "
                "(robots.txt, ToS review, Boris sign-off) before seeding a "
                "new brochure_url."
            ),
        )

    result = await db.execute(
        select(Store).where(Store.slug == store_slug)
    )
    store = result.scalars().first()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    store.brochure_url = body.brochure_url
    await db.commit()

    return StoreBrochureUrlOut(
        store_slug=store_slug,
        brochure_url=body.brochure_url,
        message=(
            f"brochure_url updated for {store_slug!r}. "
            "Run the scraper to verify: POST /admin/scrapers/run/{store_slug}"
        ),
    )


# ---------- Queue control ----------


def _extract_slug_from_celery_message(raw: bytes) -> str | None:
    """Extract the store slug from a raw Celery queue message.

    Celery encodes task arguments as base64 JSON inside a wrapper envelope.
    The body decodes to ``[[store_slug], {}, {...}]``.  As a fallback we also
    try ``headers.argsrepr`` which looks like ``"('kaufland',)"``.

    Args:
        raw: Raw bytes of a single Redis list entry.

    Returns:
        Store slug string, or ``None`` if not parseable.
    """
    import base64
    import re as _re

    try:
        msg = json.loads(raw)
        # Try headers.argsrepr first (cheapest)
        argsrepr: str = msg.get("headers", {}).get("argsrepr", "")
        if argsrepr:
            m = _re.search(r"['\"]([a-z0-9_-]+)['\"]", argsrepr)
            if m:
                return m.group(1)
        # Fall back to decoding the body
        body_b64: str = msg.get("body", "")
        if body_b64:
            body_json = base64.b64decode(body_b64 + "==").decode("utf-8", errors="replace")
            body = json.loads(body_json)
            # body is [[args...], kwargs, options]
            if isinstance(body, list) and body and isinstance(body[0], list) and body[0]:
                return str(body[0][0])
    except Exception:  # noqa: BLE001
        pass
    return None


@router.get("/scrapers/queue", response_model=QueueStatusOut)
async def get_scraper_queue(
    _key: Annotated[str, Depends(verify_admin_key)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> QueueStatusOut:
    """Return the pending Celery queue with per-store visibility.

    Parses each message in the Celery Redis queue to extract the store slug,
    and queries the DB for stores currently marked as ``running``.

    Args:
        _key: Validated admin API key (injected).
        db: Async database session (injected).

    Returns:
        Queue depth, actively running slugs, and queued-but-not-started slugs.
    """
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        # Read all messages in the Celery queue (up to 200 for safety)
        raw_messages = await r.lrange("celery", 0, 199)
    finally:
        await r.aclose()

    # Parse slugs from queue messages
    queued_slugs: list[str] = []
    seen_queued: set[str] = set()
    for raw in raw_messages:
        slug = _extract_slug_from_celery_message(raw)
        if slug and slug not in seen_queued:
            seen_queued.add(slug)
            queued_slugs.append(slug)

    # Find stores currently running (from DB)
    from sqlalchemy import and_
    subq = (
        select(
            ScrapeRun.store_id,
            func.max(ScrapeRun.started_at).label("max_started_at"),
        )
        .group_by(ScrapeRun.store_id)
        .subquery()
    )
    runs_result = await db.execute(
        select(ScrapeRun, Store.slug).join(
            subq,
            and_(
                ScrapeRun.store_id == subq.c.store_id,
                ScrapeRun.started_at == subq.c.max_started_at,
            ),
        ).join(Store, Store.id == ScrapeRun.store_id)
        .where(ScrapeRun.status == ScrapeStatus.RUNNING)
    )
    active_slugs = [row[1] for row in runs_result.all()]

    return QueueStatusOut(
        pending=len(raw_messages),
        active=active_slugs,
        queued=queued_slugs,
    )


@router.delete("/scrapers/queue", response_model=QueueClearOut)
async def clear_scraper_queue(
    _key: Annotated[str, Depends(verify_admin_key)],
) -> QueueClearOut:
    """Purge all pending (not yet started) Celery tasks from the queue.

    The currently running task is not affected.

    Args:
        _key: Validated admin API key (injected).

    Returns:
        Number of tasks cleared.
    """
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        pending = int(await r.llen("celery"))
        if pending > 0:
            await r.delete("celery")
    finally:
        await r.aclose()

    return QueueClearOut(cleared=pending)


@router.get("/scrapers/logs", response_model=list[LogEntryOut])
async def get_scraper_logs(
    _key: Annotated[str, Depends(verify_admin_key)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[LogEntryOut]:
    """Return recent scraper log entries from Redis (newest first).

    Args:
        _key: Validated admin API key (injected).
        limit: Max number of entries to return (default 100, max 200).

    Returns:
        List of log entries, most recent first.
    """
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    r = aioredis.from_url(settings.REDIS_URL)
    try:
        raw = await r.lrange("scraper:logs", 0, limit - 1)
    finally:
        await r.aclose()

    entries: list[LogEntryOut] = []
    for item in raw:
        try:
            data = json.loads(item)
            entries.append(
                LogEntryOut(
                    ts=data.get("ts", ""),
                    store=data.get("store", ""),
                    level=data.get("level", "INFO"),
                    msg=data.get("msg", ""),
                )
            )
        except Exception:  # noqa: BLE001
            pass
    return entries
