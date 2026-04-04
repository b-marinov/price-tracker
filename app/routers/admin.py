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

    model_config = {"from_attributes": True}


class PaginatedPendingProducts(PydanticBaseModel):
    """Paginated response for pending products."""

    items: list[PendingProductOut]
    total: int
    page: int
    page_size: int


class ProductActionOut(PydanticBaseModel):
    """Response schema for approve/reject actions."""

    id: uuid.UUID
    status: str
    message: str


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

    # For each product, find store names that have prices linked
    items: list[PendingProductOut] = []
    for product in products:
        store_result = await db.execute(
            select(Store.name)
            .join(Price, Price.store_id == Store.id)
            .where(Price.product_id == product.id)
            .distinct()
        )
        store_names: list[str] = list(store_result.scalars().all())

        items.append(
            PendingProductOut(
                id=product.id,
                name=product.name,
                brand=product.brand,
                barcode=product.barcode,
                created_at=product.created_at,
                matched_store_names=store_names,
            )
        )

    return PaginatedPendingProducts(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
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

    product.status = ProductStatus.ACTIVE  # type: ignore[assignment]
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
