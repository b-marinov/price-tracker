"""Scrape result pipeline — normalise and upsert Price records."""

from __future__ import annotations

import base64
import dataclasses
import logging
import os
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.price import Price, PriceSource
from app.models.store import Store
from app.scrapers.base import ScrapedItem
from app.scrapers.brand_utils import normalise_brand
from app.scrapers.catalog_matcher import get_catalog_matcher
from app.scrapers.matching import _extract_pack_components, find_or_create_product

logger = logging.getLogger(__name__)

_IMAGES_DIR = Path(os.getenv("APP_MEDIA_DIR", "/app/media")) / "images"


def _save_product_image(product_id: uuid.UUID, image_b64: str) -> str | None:
    """Decode a base64 image and save it to the media directory.

    Args:
        product_id: UUID used as the filename (ensures one image per product).
        image_b64: Base64-encoded JPEG or PNG bytes from the LLM extraction.

    Returns:
        Relative URL path (e.g. ``/media/images/{uuid}.jpg``) or None on failure.
    """
    try:
        _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        image_bytes = base64.b64decode(image_b64)
        dest = _IMAGES_DIR / f"{product_id}.jpg"
        dest.write_bytes(image_bytes)
        return f"/media/images/{product_id}.jpg"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save product image for %s: %s", product_id, exc)
        return None


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


def _normalize_currency(raw: str) -> str:
    """Normalize legacy Bulgarian currency codes to EUR.

    Bulgaria adopted the Euro in January 2025.  LLMs and older scrapers
    may still return 'лв', 'ЛВ', or 'BGN' — all map to EUR.

    Args:
        raw: Currency string as returned by the scraper or LLM.

    Returns:
        Normalised ISO 4217 currency code (always 'EUR' for BG stores).
    """
    if raw.upper() in {"ЛВ", "LV", "BGN", "ЛВ."}:
        return "EUR"
    return raw.upper() if raw else "EUR"


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
        # Reject names that are clearly not product names: single words that
        # are pure adjectives / language / origin markers (e.g. "Български",
        # "Свежи", "Нови") or are shorter than 2 characters.
        _name_stripped = item.name.strip()
        if len(_name_stripped) < 2:
            logger.debug("Skipping item with too-short name: %r", _name_stripped)
            skipped += 1
            continue
        if re.fullmatch(
            r"(Български[аяоеиу]?|Прясн[аяоеиу]|Нов[аяоеиу]?|Свеж[аяоеиу]?|"
            r"Специаленъ?|Избран[аяоеиу]?|Домашн[аяоеиу]?|Натурален?|"
            r"Пресни?|Зимни?|Лятн[аяоеиу]?)",
            _name_stripped,
            re.IGNORECASE,
        ):
            logger.warning("Skipping non-product name: %r", _name_stripped)
            skipped += 1
            continue

        # Use a savepoint so a single bad item doesn't roll back the whole batch.
        try:
            async with db.begin_nested():
                raw = item.raw or {}

                # Resolve brand and pack_info BEFORE product matching so the
                # SKU key (name + brand + generic_pack) is fully known upfront.
                raw_brand = raw.get("brand")
                brand = await normalise_brand(raw_brand, db)
                pack_info = raw.get("pack_info") or None
                additional_info = raw.get("additional_info") or None

                # ── Catalog matching ─────────────────────────────────────────
                # Map the raw scraped title to a canonical catalog name so the
                # same product from different stores lands on the same Product
                # record, enabling cross-store price comparison.
                catalog_hit = get_catalog_matcher().match(
                    item.name,
                    brand=brand,
                    pack_info=pack_info,
                    additional_info=additional_info,
                )
                if catalog_hit:
                    item = dataclasses.replace(item, name=catalog_hit.catalog_name)
                    brand = catalog_hit.brand
                    pack_info = catalog_hit.pack_info
                    additional_info = catalog_hit.additional_info
                    category_override = catalog_hit.category
                else:
                    category_override = raw.get("category")

                # Extract pack_type from full pack_info for storage
                _, pack_type = _extract_pack_components(pack_info)

                product, _created = await find_or_create_product(
                    item, db, brand=brand, pack_info=pack_info,
                    additional_info=additional_info,
                )

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
                    category_id = await _resolve_category_id(db, category_override)
                    if category_id is not None:
                        product.category_id = category_id

                # Save product image from LLM extraction (base64 → disk)
                image_url: str | None = raw.get("image_url") or None
                if not image_url:
                    image_b64 = raw.get("image_b64")
                    if image_b64:
                        image_url = _save_product_image(product.id, image_b64)
                        # Back-fill product.image_url on first discovery
                        if image_url and not product.image_url:
                            product.image_url = image_url

                price = Price(
                    product_id=product.id,
                    store_id=store.id,
                    price=item.price,
                    currency=_normalize_currency(item.currency),
                    source=_map_source(item.source),
                    brand=brand,
                    product_type=raw.get("product_type"),
                    category=raw.get("category"),
                    top_category=raw.get("top_category"),
                    unit=item.unit,
                    pack_info=raw.get("pack_info"),
                    pack_type=raw.get("pack_type"),
                    original_price=(
                        Decimal(str(raw["original_price"]))
                        if raw.get("original_price")
                        else None
                    ),
                    discount_percent=raw.get("discount_percent"),
                    image_url=image_url,
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
