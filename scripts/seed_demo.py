"""Seed the database with demo stores, categories, products, and prices.

Run inside the api container:
    docker compose -f docker-compose.dev.yml exec api python scripts/seed_demo.py

Or via make:
    docker compose -f docker-compose.dev.yml exec api python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[call-overload]


async def seed() -> None:
    """Insert demo data: 4 stores, categories, products, prices."""
    async with AsyncSessionLocal() as db:
        # ── Stores ────────────────────────────────────────────────────────────
        stores = [
            {"name": "Kaufland България", "slug": "kaufland",    "website_url": "https://www.kaufland.bg",  "logo_url": None},
            {"name": "Lidl България",     "slug": "lidl",        "website_url": "https://www.lidl.bg",      "logo_url": None},
            {"name": "Billa България",    "slug": "billa",       "website_url": "https://ssm.billa.bg",     "logo_url": None},
            {"name": "Fantastico",        "slug": "fantastico",  "website_url": "https://fantastico.bg",    "logo_url": None},
        ]
        store_ids: dict[str, uuid.UUID] = {}
        for s in stores:
            existing = await db.execute(
                text("SELECT id FROM stores WHERE slug = :slug"),
                {"slug": s["slug"]},
            )
            row = existing.fetchone()
            if row:
                store_ids[s["slug"]] = row[0]
                print(f"  store exists: {s['name']}")
            else:
                sid = uuid.uuid4()
                await db.execute(
                    text("""
                        INSERT INTO stores (id, name, slug, website_url, logo_url, active,
                                           created_at, updated_at)
                        VALUES (:id, :name, :slug, :website_url, :logo_url, true,
                                now(), now())
                    """),
                    {**s, "id": str(sid)},
                )
                store_ids[s["slug"]] = sid
                print(f"  created store: {s['name']}")

        # ── Categories ────────────────────────────────────────────────────────
        categories_def = [
            {"name": "Мляко и млечни",   "slug": "dairy",     "parent": None},
            {"name": "Хляб и хлебни",    "slug": "bread",     "parent": None},
            {"name": "Месо и птиче",     "slug": "meat",      "parent": None},
            {"name": "Напитки",          "slug": "drinks",    "parent": None},
            {"name": "Плодове и зеленчуци", "slug": "produce", "parent": None},
            {"name": "Битова химия",     "slug": "household", "parent": None},
        ]
        cat_ids: dict[str, uuid.UUID] = {}
        for c in categories_def:
            existing = await db.execute(
                text("SELECT id FROM categories WHERE slug = :slug"),
                {"slug": c["slug"]},
            )
            row = existing.fetchone()
            if row:
                cat_ids[c["slug"]] = row[0]
            else:
                cid = uuid.uuid4()
                await db.execute(
                    text("""
                        INSERT INTO categories (id, name, slug, parent_id, created_at, updated_at)
                        VALUES (:id, :name, :slug, :parent_id, now(), now())
                    """),
                    {"id": str(cid), "name": c["name"], "slug": c["slug"], "parent_id": None},
                )
                cat_ids[c["slug"]] = cid
                print(f"  created category: {c['name']}")

        # ── Products + prices ─────────────────────────────────────────────────
        products = [
            {
                "name": "Прясно мляко 3.5% мазнини 1л",
                "slug": "prasno-mlqko-3-5",
                "brand": "Млечна ферма",
                "category": "dairy",
                "barcode": "3800000000001",
                "prices": {
                    "kaufland": Decimal("1.99"),
                    "lidl":     Decimal("1.89"),
                    "billa":    Decimal("2.09"),
                    "fantastico": Decimal("1.95"),
                },
            },
            {
                "name": "Кисело мляко 2% 400г",
                "slug": "kiselo-mlqko-2",
                "brand": "Верея",
                "category": "dairy",
                "barcode": "3800000000002",
                "prices": {
                    "kaufland": Decimal("1.29"),
                    "lidl":     Decimal("1.19"),
                    "billa":    Decimal("1.39"),
                    "fantastico": Decimal("1.25"),
                },
            },
            {
                "name": "Бял хляб 500г",
                "slug": "bql-hlyab-500g",
                "brand": None,
                "category": "bread",
                "barcode": "3800000000003",
                "prices": {
                    "kaufland": Decimal("0.79"),
                    "lidl":     Decimal("0.75"),
                    "billa":    Decimal("0.89"),
                    "fantastico": Decimal("0.82"),
                },
            },
            {
                "name": "Пълнозърнест хляб 400г",
                "slug": "pulnozarnest-hlyab",
                "brand": "Добруджа",
                "category": "bread",
                "barcode": "3800000000004",
                "prices": {
                    "kaufland": Decimal("1.49"),
                    "lidl":     Decimal("1.39"),
                    "billa":    Decimal("1.59"),
                },
            },
            {
                "name": "Пилешко филе 1кг",
                "slug": "pileshko-file-1kg",
                "brand": None,
                "category": "meat",
                "barcode": "3800000000005",
                "prices": {
                    "kaufland": Decimal("8.99"),
                    "lidl":     Decimal("8.49"),
                    "billa":    Decimal("9.49"),
                    "fantastico": Decimal("8.79"),
                },
            },
            {
                "name": "Минерална вода 1.5л",
                "slug": "mineralna-voda-1-5",
                "brand": "Девин",
                "category": "drinks",
                "barcode": "3800000000006",
                "prices": {
                    "kaufland": Decimal("0.59"),
                    "lidl":     Decimal("0.55"),
                    "billa":    Decimal("0.65"),
                    "fantastico": Decimal("0.58"),
                },
            },
            {
                "name": "Портокалов сок 1л",
                "slug": "portokalov-sok-1l",
                "brand": "Cappy",
                "category": "drinks",
                "barcode": "3800000000007",
                "prices": {
                    "kaufland": Decimal("2.49"),
                    "billa":    Decimal("2.69"),
                    "fantastico": Decimal("2.55"),
                },
            },
            {
                "name": "Домати 1кг",
                "slug": "domati-1kg",
                "brand": None,
                "category": "produce",
                "barcode": None,
                "prices": {
                    "kaufland": Decimal("2.99"),
                    "lidl":     Decimal("2.79"),
                    "billa":    Decimal("3.19"),
                    "fantastico": Decimal("2.89"),
                },
            },
            {
                "name": "Краставици 1кг",
                "slug": "krastavici-1kg",
                "brand": None,
                "category": "produce",
                "barcode": None,
                "prices": {
                    "kaufland": Decimal("1.79"),
                    "lidl":     Decimal("1.69"),
                    "billa":    Decimal("1.99"),
                },
            },
            {
                "name": "Прах за пране 3кг",
                "slug": "prah-za-prane-3kg",
                "brand": "Ariel",
                "category": "household",
                "barcode": "3800000000010",
                "prices": {
                    "kaufland": Decimal("12.99"),
                    "lidl":     Decimal("11.99"),
                    "billa":    Decimal("13.49"),
                    "fantastico": Decimal("12.49"),
                },
            },
        ]

        now = datetime.now(tz=timezone.utc)

        for p in products:
            existing = await db.execute(
                text("SELECT id FROM products WHERE slug = :slug"),
                {"slug": p["slug"]},
            )
            row = existing.fetchone()
            if row:
                product_id = row[0]
                print(f"  product exists: {p['name']}")
            else:
                product_id = uuid.uuid4()
                await db.execute(
                    text("""
                        INSERT INTO products
                            (id, name, slug, brand, category_id, barcode, status,
                             created_at, updated_at)
                        VALUES
                            (:id, :name, :slug, :brand, :category_id, :barcode, 'active',
                             now(), now())
                    """),
                    {
                        "id": str(product_id),
                        "name": p["name"],
                        "slug": p["slug"],
                        "brand": p["brand"],
                        "category_id": str(cat_ids[p["category"]]),
                        "barcode": p["barcode"],
                    },
                )
                print(f"  created product: {p['name']}")

            for store_slug, price in p["prices"].items():  # type: ignore[union-attr]
                await db.execute(
                    text("""
                        INSERT INTO prices
                            (id, product_id, store_id, price, currency, source,
                             recorded_at, created_at, updated_at)
                        VALUES
                            (gen_random_uuid(), :product_id, :store_id, :price, 'EUR',
                             'seed', :recorded_at, now(), now())
                    """),
                    {
                        "product_id": str(product_id),
                        "store_id": str(store_ids[store_slug]),
                        "price": price,
                        "recorded_at": now,
                    },
                )

        await db.commit()
        print("\n✓ Seed complete.")
        print(f"  {len(stores)} stores, {len(categories_def)} categories, {len(products)} products")


if __name__ == "__main__":
    asyncio.run(seed())
