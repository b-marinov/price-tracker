"""Product matching logic — SKU-level identity via name + brand + generic_pack.

A Product represents a product family with pack variants. Matching uses three keys:

* **name** — normalised generic product type ("бира", "кисело мляко")
* **brand** — normalised brand name ("heineken", "danone") or None
* **generic_pack** — normalised pack size string ("0.5 л", "1 кг") or None

Pack variants (e.g. "кенче" vs "пакет" for same pack size) are treated as
variants of the same product family. The ``pack_type`` field on Product stores
the packaging material/type but doesn't affect matching.

Uses ``rapidfuzz`` for fuzzy name comparison only; brand and generic_pack
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


# Packaging type keywords (Bulgarian packaging materials)
_PACK_TYPE_KEYWORDS: list[str] = [
    "кенче",
    "пакет",
    "кутия",
    "бутилка",
    "стъкло",
    "пластмасова",
    "консерва",
    "боричка",
    "чефтер",
    "сак",
    "саксия",
    "кашон",
    "свещи",
    "кутия",
    "пак",
    "промопакет",
    "запаян",
    "под ключ",
    "бидон",
    "типа",
    "капса",
]


def _extract_pack_components(raw: str | None) -> tuple[str | None, str | None]:
    """Extract generic_pack and pack_type from full pack_info string.

    Splits pack_info into size/quantity (generic_pack) and packaging type
    (pack_type). The order in the original string is preserved.

    Args:
        raw: Full pack_info string like "1 кг кенче" or "500 г пакет".

    Returns:
        Tuple of (generic_pack, pack_type) — e.g. ("1 кг", "кенче") or
        ("500 г", None) if no packaging type detected.
    """
    if not raw:
        return None, None

    # First normalize the full string
    value = raw.strip().lower()
    value = re.sub(r"(\d),(\d)", r"\1.\2", value)
    value = re.sub(r"\s+", " ", value)

    # Try to find packaging type in the string
    pack_type: str | None = None
    generic_pack: str | None = None

    for keyword in _PACK_TYPE_KEYWORDS:
        if keyword in value:
            # Extract the keyword as pack_type
            pack_type = keyword
            # Everything else is generic_pack
            remaining = re.sub(rf"\b{re.escape(keyword)}\b", "", value, flags=re.IGNORECASE)
            generic_pack = remaining.strip() or None
            break

    # If no pack_type found, treat entire string as generic_pack
    if pack_type is None:
        generic_pack = value or None

    return generic_pack, pack_type or None


def normalise_pack_info(raw: str | None) -> str | None:
    """Normalise a full pack_info string for display/backward compatibility.

    Args:
        raw: Full pack_info string as returned by the LLM.

    Returns:
        Normalised full pack_info string, or None if input is None/empty.
    """
    if not raw:
        return None
    value = raw.strip().lower()
    value = re.sub(r"(\d),(\d)", r"\1.\2", value)
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
    pack_info: str | None = None,
) -> Product | None:
    """Find the best product match by (fuzzy name, brand, generic_pack).

    Pack variants (different pack_type like "кенче" vs "пакет") are treated
    as variants of the same product family. Matching uses:
    1. Fuzzy name (>= FUZZY_THRESHOLD) + exact brand + exact generic_pack.
    2. Branded-only fallback: exact brand + non-trivial generic_pack.

    Args:
        db: The async database session.
        item_name: Product type/variant name from the scraper/LLM.
        brand: Normalised brand name, or None for unbranded items.
        pack_info: Full pack_info string from LLM (e.g. "1 кг кенче").

    Returns:
        The best-matching Product, or None.
    """
    normalised_input = normalise_name(item_name)
    norm_brand = _normalise_brand(brand)

    # Extract generic_pack from full pack_info (if provided)
    _, item_pack_type = _extract_pack_components(pack_info)
    generic_pack, item_pack_type = _extract_pack_components(pack_info)
    item_generic_pack = generic_pack

    result = await db.execute(select(Product))
    products: list[Product] = list(result.scalars().all())

    best_product: Product | None = None
    best_score: float = 0.0
    brand_pack_fallback: Product | None = None

    for product in products:
        # Skip if brands don't match
        if _normalise_brand(product.brand) != norm_brand:
            continue

        # Get product's generic_pack and pack_type
        prod_generic = product.generic_pack
        prod_pack_type = product.pack_type

        # If both have generic_pack, they must match exactly
        if prod_generic and item_generic_pack:
            if normalise_pack_info(prod_generic) != normalise_pack_info(item_generic_pack):
                continue

        # If only one has generic_pack, only match if both are None
        # (product without pack_type matches any variant of same name+brand)
        if prod_generic is None and item_generic_pack is not None:
            # Item has pack size but product doesn't — skip match
            continue

        score = fuzz.ratio(normalised_input, normalise_name(product.name))
        if score > best_score:
            best_score = score
            best_product = product

        # Track branded fallback candidate (brand + generic_pack match, any name)
        if (
            brand_pack_fallback is None
            and norm_brand is not None
            and item_generic_pack is not None
            and any(c.isdigit() for c in normalise_pack_info(item_generic_pack) or "")
        ):
            brand_pack_fallback = product

    if best_score >= FUZZY_THRESHOLD and best_product is not None:
        logger.debug(
            "Product match (name+brand+generic_pack): '%s' / brand=%r / pack=%r -> product %s (score=%.1f)",
            item_name, brand, pack_info, best_product.id, best_score,
        )
        return best_product

    if brand_pack_fallback is not None:
        logger.debug(
            "Product match (brand+pack fallback): '%s' / brand=%r / pack=%r -> product %s",
            item_name, brand, pack_info, brand_pack_fallback.id,
        )
        return brand_pack_fallback

    return None


async def find_or_create_product(
    item: ScrapedItem,
    db: AsyncSession,
    *,
    brand: str | None,
    pack_info: str | None = None,
    additional_info: str | None = None,
) -> tuple[Product, bool]:
    """Match a scraped item to an existing product family, or create a new one.

    A Product represents a product family with pack variants. Matching strategy:

    1. Exact barcode match (if barcode is present).
    2. Product match: fuzzy name (>= 90%) AND exact brand AND matching generic_pack.
    3. Create a new Product with ``status=pending_review``.

    Pack variants (different pack_type like "кенче" vs "пакет") are stored
    on the same product and appear as variants on the product page.

    Args:
        item: The scraped item to match against existing products.
        db: The async database session.
        brand: Pre-resolved canonical brand name (from brand_utils).
        pack_info: Full pack_info string from LLM extraction (e.g. "1 кг кенче").

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

    # 2. Product match: name + brand + generic_pack
    product = await _match_by_sku(db, item.name, brand, pack_info)
    if product is not None:
        if additional_info and not product.additional_info:
            product.additional_info = additional_info
        return product, False

    # 3. Create new product family
    slug = _slugify(item.name, item.barcode)
    generic_pack, pack_type = _extract_pack_components(pack_info)

    product = Product(
        name=item.name,
        slug=slug,
        brand=brand,
        generic_pack=generic_pack,
        pack_type=pack_type,
        pack_info=normalise_pack_info(pack_info),  # For backward compatibility
        additional_info=additional_info or None,
        barcode=item.barcode,
        image_url=item.image_url,
        status=ProductStatus.PENDING_REVIEW,
    )
    db.add(product)
    await db.flush()
    logger.info(
        "Created new product family: %s / brand=%r / pack=%r (slug=%s, pack_type=%r)",
        item.name,
        brand,
        pack_info,
        slug,
        pack_type,
    )
    return product, True
