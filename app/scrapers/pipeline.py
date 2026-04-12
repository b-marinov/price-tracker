"""Scrape result pipeline — normalise and upsert Price records."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.price import Price, PriceSource
from app.models.product import Product, ProductStatus
from app.models.store import Store
from app.scrapers.base import ScrapedItem
from app.scrapers.brand_utils import normalise_brand
from app.scrapers.matching import find_or_create_product

logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    """Create a URL-friendly slug from a product name.

    Args:
        name: The product name to slugify.

    Returns:
        A lowercase, hyphen-separated slug string.
    """
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-")


async def _get_store(db: AsyncSession, store_slug: str) -> Store | None:
    """Look up a store by its slug.

    Args:
        db: The async database session.
        store_slug: Unique slug for the store.

    Returns:
        The Store instance if found, else None.
    """
    result = await db.execute(
        select(Store).where(Store.slug == store_slug)
    )
    return result.scalars().first()


async def _find_or_create_product(
    db: AsyncSession,
    item: ScrapedItem,
) -> Product:
    """Find an existing product by barcode or normalised name, or create one.

    Lookup strategy:
    1. If the item has a barcode, search by barcode.
    2. Otherwise, search by exact normalised name.
    3. If no match, create a new Product with status=pending_review.

    Args:
        db: The async database session.
        item: The scraped item to match.

    Returns:
        An existing or newly created Product.
    """
    if item.barcode:
        result = await db.execute(
            select(Product).where(Product.barcode == item.barcode)
        )
        product = result.scalars().first()
        if product:
            return product

    # Fall back to normalised name match
    result = await db.execute(
        select(Product).where(Product.name == item.name)
    )
    product = result.scalars().first()
    if product:
        return product

    # Create new product
    slug = _slugify(item.name)
    # Ensure slug uniqueness by appending barcode fragment if available
    if item.barcode:
        slug = f"{slug}-{item.barcode[-4:]}"

    product = Product(
        name=item.name,
        slug=slug,
        barcode=item.barcode,
        image_url=item.image_url,
        status=ProductStatus.PENDING_REVIEW,
    )
    db.add(product)
    await db.flush()  # assign id without committing
    return product


async def _price_exists_today(
    db: AsyncSession,
    product_id: object,
    store_id: object,
    brand: str | None,
) -> bool:
    """Check whether a Price record already exists for today.

    The dedup key is (product_id, store_id, brand) so that different brands
    of the same generic product at the same store each get their own Price row.
    For example, Milka chocolate and Nestlé chocolate both map to the same
    "Шоколадови Бонбони" Product but produce distinct Price rows.

    Args:
        db: The async database session.
        product_id: UUID of the product.
        store_id: UUID of the store.
        brand: Brand name from the scraped item (may be None for unbranded).

    Returns:
        True if a price for this product+store+brand was already recorded today.
    """
    today = date.today()
    start_of_day = datetime(today.year, today.month, today.day, tzinfo=UTC)
    end_of_day = datetime(
        today.year, today.month, today.day, 23, 59, 59, tzinfo=UTC
    )
    q = (
        select(Price.id)
        .where(Price.product_id == product_id)
        .where(Price.store_id == store_id)
        .where(Price.recorded_at >= start_of_day)
        .where(Price.recorded_at <= end_of_day)
    )
    q = q.where(Price.brand.is_(None)) if brand is None else q.where(Price.brand == brand)
    result = await db.execute(q.limit(1))
    return result.scalars().first() is not None


async def _resolve_category_id(
    db: AsyncSession,
    category_name: str | None,
) -> uuid.UUID | None:
    """Return the Category.id for a given category name, or None if not found.

    Args:
        db: The async database session.
        category_name: The raw category string extracted by the LLM.

    Returns:
        UUID of the matching Category, or None.
    """
    if not category_name:
        return None
    result = await db.execute(
        select(Category.id).where(Category.name == category_name)
    )
    return result.scalars().first()


def _map_source(source_str: str) -> PriceSource:
    """Map a scraped item source string to the PriceSource enum.

    Args:
        source_str: One of "web" or "brochure".

    Returns:
        The corresponding PriceSource enum member.
    """
    if source_str == "brochure":
        return PriceSource.BROCHURE
    return PriceSource.WEB


async def process_scrape(
    store_slug: str,
    items: list[ScrapedItem],
    db: AsyncSession,
) -> int:
    """Process scraped items: find/create products, deduplicate, insert prices.

    For each ScrapedItem:
    1. Look up the Store by slug.
    2. Find or create the Product by barcode (if present), else by name.
    3. Skip if a Price already exists for (product_id, store_id) today.
    4. Insert a new Price record.

    Args:
        store_slug: The slug of the store being scraped.
        items: Normalised ScrapedItem instances from the scraper.
        db: The async database session.

    Returns:
        Count of new Price records inserted.

    Raises:
        ValueError: If the store_slug does not match any known store.
    """
    store = await _get_store(db, store_slug)
    if store is None:
        raise ValueError(f"Store not found for slug: {store_slug!r}")

    inserted = 0
    skipped = 0
    for item in items:
        # Use a savepoint so a single bad item doesn't roll back the whole batch.
        try:
            async with db.begin_nested():
                product, _created = await find_or_create_product(item, db)

                raw = item.raw or {}
                raw_brand = raw.get("brand")
                brand = await normalise_brand(raw_brand, db)

                if await _price_exists_today(db, product.id, store.id, brand):
                    logger.debug(
                        "Skipping duplicate price for product=%s store=%s brand=%s",
                        product.id,
                        store.id,
                        brand,
                    )
                    skipped += 1
                    continue

                # Link product to category if not already set
                if product.category_id is None:
                    category_id = await _resolve_category_id(
                        db, raw.get("category")
                    )
                    if category_id is not None:
                        product.category_id = category_id
                price = Price(
                    product_id=product.id,
                    store_id=store.id,
                    price=item.price,
                    currency=item.currency,
                    source=_map_source(item.source),
                    brand=brand,
                    product_type=raw.get("product_type"),
                    category=raw.get("category"),
                    top_category=raw.get("top_category"),
                    original_price=(
                        Decimal(str(raw["original_price"]))
                        if raw.get("original_price")
                        else None
                    ),
                    discount_percent=raw.get("discount_percent"),
                    image_url=raw.get("image_url"),
                )
                db.add(price)
                inserted += 1
        except Exception as exc:
            logger.warning("Skipping item %r due to error: %s", item.name, exc)
            skipped += 1

    await db.commit()
    logger.info(
        "Processed %d items for store %s — %d new prices inserted",
        len(items),
        store_slug,
        inserted,
    )
    return inserted
