"""Store and brochure API endpoints.

Provides store listing and per-store brochure access (current flyer + history).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.brochure import Brochure
from app.models.store import Store
from app.schemas.brochure import BrochureResponse, StoreResponse

router = APIRouter(prefix="/stores", tags=["stores"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _to_brochure_response(b: Brochure) -> BrochureResponse:
    """Convert a Brochure ORM instance to its response schema.

    Args:
        b: ORM Brochure instance (with store relationship loaded).

    Returns:
        BrochureResponse schema.
    """
    return BrochureResponse(
        id=b.id,
        store_id=uuid.UUID(str(b.store_id)),
        store_name=b.store.name,
        store_slug=b.store.slug,
        title=b.title,
        pdf_url=b.pdf_url,
        valid_from=b.valid_from,
        valid_to=b.valid_to,
        is_current=b.is_current,
        created_at=b.created_at,
    )


@router.get("", response_model=list[StoreResponse])
async def list_stores(db: DbSession) -> list[StoreResponse]:
    """Return all active tracked stores.

    Args:
        db: Async database session.

    Returns:
        List of StoreResponse objects for all active stores.
    """
    stmt = select(Store).where(Store.active.is_(True)).order_by(Store.name)
    stores = list((await db.execute(stmt)).scalars().all())
    return [StoreResponse.model_validate(s) for s in stores]


@router.get("/brochures/active", response_model=list[BrochureResponse])
async def list_active_brochures(db: DbSession) -> list[BrochureResponse]:
    """Return all currently active brochures across all stores.

    Used to populate the brochure index page showing the latest flyer
    from every store.

    Args:
        db: Async database session.

    Returns:
        List of BrochureResponse for every store's current brochure.
    """
    stmt = (
        select(Brochure)
        .where(Brochure.is_current.is_(True))
        .order_by(Brochure.valid_from.desc())
    )
    brochures = list((await db.execute(stmt)).scalars().all())
    return [_to_brochure_response(b) for b in brochures]


@router.get("/{store_id}/brochures", response_model=list[BrochureResponse])
async def list_store_brochures(
    store_id: uuid.UUID,
    db: DbSession,
) -> list[BrochureResponse]:
    """Return all brochures for a store, most recent first.

    Args:
        store_id: UUID of the store.
        db: Async database session.

    Returns:
        List of BrochureResponse objects ordered by valid_from descending.

    Raises:
        HTTPException: 404 if the store does not exist.
    """
    store = (
        await db.execute(select(Store).where(Store.id == store_id))
    ).scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        )

    stmt = (
        select(Brochure)
        .where(Brochure.store_id == str(store_id))
        .order_by(Brochure.valid_from.desc())
    )
    brochures = list((await db.execute(stmt)).scalars().all())
    return [_to_brochure_response(b) for b in brochures]


@router.get("/{store_id}/brochures/current", response_model=BrochureResponse)
async def get_current_brochure(
    store_id: uuid.UUID,
    db: DbSession,
) -> BrochureResponse:
    """Return the current active brochure for a store.

    Args:
        store_id: UUID of the store.
        db: Async database session.

    Returns:
        BrochureResponse for the store's current brochure.

    Raises:
        HTTPException: 404 if the store does not exist or has no current brochure.
    """
    store = (
        await db.execute(select(Store).where(Store.id == store_id))
    ).scalar_one_or_none()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        )

    brochure = (
        await db.execute(
            select(Brochure)
            .where(Brochure.store_id == str(store_id))
            .where(Brochure.is_current.is_(True))
        )
    ).scalar_one_or_none()

    if brochure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current brochure for this store",
        )

    return _to_brochure_response(brochure)
