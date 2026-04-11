"""Product matching logic — barcode lookup + fuzzy name matching.

Uses ``rapidfuzz`` for fuzzy string comparison when an exact barcode
match is not available.  New dependency: **rapidfuzz** (flagged for
stakeholder approval).
"""

from __future__ import annotations

import logging
import re
import unicodedata

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product, ProductStatus
from app.scrapers.base import ScrapedItem

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD: float = 90.0
"""Minimum ``rapidfuzz.fuzz.ratio`` score to consider a name match."""


def normalise_name(raw: str) -> str:
    """Normalise a product name for comparison.

    * Unicode NFKD decomposition
    * Lowercase
    * Strip punctuation
    * Collapse whitespace

    Args:
        raw: The raw product name string.

    Returns:
        A cleaned, lowercased string suitable for fuzzy comparison.
    """
    value = unicodedata.normalize("NFKD", raw)
    value = value.lower()
    value = re.sub(r"[^\w\s]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _slugify(name: str, barcode: str | None = None) -> str:
    """Create a URL-friendly slug from a product name.

    Tries ASCII transliteration first. Falls back to a short UUID when the
    name is entirely non-ASCII (e.g. Cyrillic-only) and produces an empty
    string after encoding, preventing unique-constraint violations on the
    ``products.slug`` column.

    Args:
        name: The product name to slugify.
        barcode: Optional barcode to append for uniqueness.

    Returns:
        A non-empty lowercase, hyphen-separated slug string.
    """
    import uuid as _uuid

    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    slug = re.sub(r"[-\s]+", "-", value).strip("-")

    # If the name was all non-ASCII (e.g. Bulgarian Cyrillic), the slug is
    # empty — use a short UUID fragment to guarantee uniqueness.
    if not slug:
        slug = _uuid.uuid4().hex[:12]

    if barcode:
        slug = f"{slug}-{barcode[-4:]}"
    return slug


async def _match_by_barcode(
    db: AsyncSession,
    barcode: str,
) -> Product | None:
    """Look up a product by exact barcode.

    Args:
        db: The async database session.
        barcode: The barcode string to search for.

    Returns:
        The matching Product or None.
    """
    result = await db.execute(
        select(Product).where(Product.barcode == barcode)
    )
    return result.scalars().first()


async def _match_by_fuzzy_name(
    db: AsyncSession,
    item_name: str,
) -> Product | None:
    """Find the best fuzzy-matched product by normalised name.

    Loads all products and compares using ``rapidfuzz.fuzz.ratio``
    on the normalised name.  Returns the best match above
    :data:`FUZZY_THRESHOLD`, or ``None``.

    Args:
        db: The async database session.
        item_name: The scraped product name (will be normalised).

    Returns:
        The best-matching Product if score >= threshold, else None.
    """
    normalised_input = normalise_name(item_name)
    result = await db.execute(select(Product))
    products: list[Product] = list(result.scalars().all())

    best_product: Product | None = None
    best_score: float = 0.0

    for product in products:
        score = fuzz.ratio(normalised_input, normalise_name(product.name))
        if score > best_score:
            best_score = score
            best_product = product

    if best_score >= FUZZY_THRESHOLD and best_product is not None:
        logger.debug(
            "Fuzzy match: '%s' -> '%s' (score=%.1f)",
            item_name,
            best_product.name,
            best_score,
        )
        return best_product

    return None


async def find_or_create_product(
    item: ScrapedItem,
    db: AsyncSession,
) -> tuple[Product, bool]:
    """Match a scraped item to an existing product, or create a new one.

    Matching strategy (in order):
    1. Exact barcode match (if barcode is present).
    2. Fuzzy normalised-name match (>= 90 % similarity).
    3. Create a new Product with ``status=pending_review``.

    Args:
        item: The scraped item to match against existing products.
        db: The async database session.

    Returns:
        A tuple of ``(product, created)`` where *created* is ``True``
        when a brand-new Product was inserted.
    """
    # 1. Barcode lookup
    if item.barcode:
        product = await _match_by_barcode(db, item.barcode)
        if product is not None:
            return product, False

    # 2. Fuzzy name match
    product = await _match_by_fuzzy_name(db, item.name)
    if product is not None:
        return product, False

    # 3. Create new product
    slug = _slugify(item.name, item.barcode)
    product = Product(
        name=item.name,
        slug=slug,
        barcode=item.barcode,
        image_url=item.image_url,
        status=ProductStatus.PENDING_REVIEW,
    )
    db.add(product)
    await db.flush()
    logger.info("Created new pending product: %s (slug=%s)", item.name, slug)
    return product, True
