"""Utility for normalising brand names against the brand_aliases table."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_alias import BrandAlias

logger = logging.getLogger(__name__)


async def normalise_brand(brand: str | None, db: AsyncSession) -> str | None:
    """Resolve a brand name variant to its canonical form.

    Looks up the brand (case-insensitive) in brand_aliases.
    Returns the canonical name if found, otherwise returns the original.

    Args:
        brand: Raw brand name from LLM extraction, or None.
        db: Async database session.

    Returns:
        Canonical brand name, original if no alias found, or None if input is None.
    """
    if not brand:
        return brand

    result = await db.execute(
        select(BrandAlias.canonical).where(
            BrandAlias.alias == brand.strip().lower()
        )
    )
    canonical = result.scalars().first()
    if canonical:
        logger.debug("Brand normalised: %r -> %r", brand, canonical)
        return canonical
    return brand
