"""Product matching logic — SKU-level identity via name + brand + pack_info.

A Product now represents a specific SKU (e.g. "Бира / Heineken / 0.5 л")
rather than a generic type.  Matching uses three keys:

* **name** — normalised generic product type ("бира", "кисело мляко")
* **brand** — normalised brand name ("heineken", "danone") or None
* **pack_info** — normalised pack size string ("0.5 л", "1 кг") or None

Two items are considered the same SKU when all three keys agree (with None
treated as a distinct value — a product with a known pack size does not
merge with one of unknown size).

Uses ``rapidfuzz`` for fuzzy name comparison only; brand and pack_info
are compared after normalization using exact equality.
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
"""Minimum ``rapidfuzz.fuzz.ratio`` score for name component of SKU match."""


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


def normalise_pack_info(raw: str | None) -> str | None:
    """Normalise a pack size string for SKU matching.

    Applies lightweight cleanup so minor formatting differences from the
    LLM (comma vs dot decimal, extra spaces) do not cause false mismatches:

    * Strip whitespace
    * Replace comma decimal separator with dot ("0,5 л" → "0.5 л")
    * Collapse internal whitespace
    * Lowercase

    Args:
        raw: Pack info string as returned by the LLM, or None.

    Returns:
        Normalised pack info string, or None if input is None / empty.
    """
    if not raw:
        return None
    value = raw.strip().lower()
    value = re.sub(r"(\d),(\d)", r"\1.\2", value)   # "0,5" → "0.5"
    value = re.sub(r"\s+", " ", value)
    return value or None


def _normalise_brand(brand: str | None) -> str | None:
    """Lowercase + strip a brand name for comparison."""
    if not brand:
        return None
    return brand.strip().lower()


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


async def _match_by_sku(
    db: AsyncSession,
    item_name: str,
    brand: str | None,
    pack_info: str | None,
) -> Product | None:
    """Find the best SKU match by (fuzzy name, brand, pack_info).

    Matching strategy (first match wins):
    1. Fuzzy name (>= FUZZY_THRESHOLD) + exact brand + exact pack_info.
    2. Branded-only fallback: exact brand + exact pack_info when both are
       non-None and pack_info is non-trivial (contains a digit).  This
       handles cases where the same physical product has slightly different
       type names across stores (e.g. "Газирана Напитка" vs "Кока-Кола"
       both with brand="Coca-Cola" and pack_info="2 л").

    Brand and pack_info equality is always checked after normalisation.
    Pack_info=None is never used for the branded fallback — without a known
    size there is not enough signal to merge products.

    Args:
        db: The async database session.
        item_name: Product type/variant name from the scraper/LLM.
        brand: Normalised brand name, or None for unbranded items.
        pack_info: Normalised pack size string, or None if unknown.

    Returns:
        The best-matching Product, or None.
    """
    normalised_input = normalise_name(item_name)
    norm_brand = _normalise_brand(brand)
    norm_pack = normalise_pack_info(pack_info)

    result = await db.execute(select(Product))
    products: list[Product] = list(result.scalars().all())

    best_product: Product | None = None
    best_score: float = 0.0
    brand_pack_fallback: Product | None = None

    for product in products:
        if _normalise_brand(product.brand) != norm_brand:
            continue
        if normalise_pack_info(product.pack_info) != norm_pack:
            continue

        score = fuzz.ratio(normalised_input, normalise_name(product.name))
        if score > best_score:
            best_score = score
            best_product = product

        # Track branded fallback candidate (brand + pack_info match, any name)
        if (
            brand_pack_fallback is None
            and norm_brand is not None
            and norm_pack is not None
            and any(c.isdigit() for c in norm_pack)
        ):
            brand_pack_fallback = product

    if best_score >= FUZZY_THRESHOLD and best_product is not None:
        logger.debug(
            "SKU match (name+brand+pack): '%s' / brand=%r / pack=%r -> product %s (score=%.1f)",
            item_name, brand, pack_info, best_product.id, best_score,
        )
        return best_product

    if brand_pack_fallback is not None:
        logger.debug(
            "SKU match (brand+pack fallback): '%s' / brand=%r / pack=%r -> product %s",
            item_name, brand, pack_info, brand_pack_fallback.id,
        )
        return brand_pack_fallback

    return None


async def find_or_create_product(
    item: ScrapedItem,
    db: AsyncSession,
    *,
    brand: str | None,
    pack_info: str | None,
    additional_info: str | None = None,
) -> tuple[Product, bool]:
    """Match a scraped item to an existing SKU product, or create a new one.

    A Product represents a specific SKU — a combination of generic product
    type, brand, and pack size.  Matching strategy:

    1. Exact barcode match (if barcode is present).
    2. SKU match: fuzzy name (>= 90%) AND exact brand AND exact pack_info.
    3. Create a new Product with ``status=pending_review``.

    Args:
        item: The scraped item to match against existing products.
        db: The async database session.
        brand: Pre-resolved canonical brand name (from brand_utils).
        pack_info: Normalised pack size string (from LLM extraction).

    Returns:
        A tuple of ``(product, created)`` where *created* is ``True``
        when a brand-new Product was inserted.
    """
    # 1. Barcode lookup
    if item.barcode:
        product = await _match_by_barcode(db, item.barcode)
        if product is not None:
            if additional_info and not product.additional_info:
                product.additional_info = additional_info
            return product, False

    # 2. SKU match: name + brand + pack_info
    product = await _match_by_sku(db, item.name, brand, pack_info)
    if product is not None:
        if additional_info and not product.additional_info:
            product.additional_info = additional_info
        return product, False

    # 3. Create new SKU product
    slug = _slugify(item.name, item.barcode)
    product = Product(
        name=item.name,
        slug=slug,
        brand=brand,
        pack_info=normalise_pack_info(pack_info),
        additional_info=additional_info or None,
        barcode=item.barcode,
        image_url=item.image_url,
        status=ProductStatus.PENDING_REVIEW,
    )
    db.add(product)
    await db.flush()
    logger.info(
        "Created new SKU product: %s / brand=%r / pack=%r (slug=%s)",
        item.name,
        brand,
        pack_info,
        slug,
    )
    return product, True
