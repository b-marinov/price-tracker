"""seed grocery category taxonomy into categories table

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-11

Inserts the full LLM grocery taxonomy (top-level + sub-categories) that
mirrors GROCERY_CATEGORIES / CATEGORY_HIERARCHY in app/scrapers/llm_parser.py.
Uses uuid5(DNS, name) so UUIDs are stable and deterministic across environments.
Idempotent — skips rows that already exist.
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op

# Revision identifiers
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

# Use DNS namespace for deterministic UUIDs from category names
_NS = uuid.NAMESPACE_DNS


def _uid(name: str) -> str:
    return str(uuid.uuid5(_NS, f"category:{name}"))


# Top-level categories (parent_id = NULL)
_TOP_CATEGORIES: list[str] = [
    "Млечни продукти",
    "Месо, риба и колбаси",
    "Плодове и зеленчуци",
    "Хляб, тестени и зърнени",
    "Сладкиши и снаксове",
    "Напитки",
    "Подправки и консерви",
    "Специални",
    "Домашни любимци",
    "Дом и хигиена",
    "Нехранителни стоки",
    "Друго",
]

# Sub-category → top-level parent mapping (mirrors CATEGORY_HIERARCHY)
_SUB_CATEGORIES: list[tuple[str, str]] = [
    ("Сирене", "Млечни продукти"),
    ("Кисело мляко", "Млечни продукти"),
    ("Прясно мляко", "Млечни продукти"),
    ("Краве масло и маргарин", "Млечни продукти"),
    ("Яйца", "Млечни продукти"),
    ("Сметана и крем", "Млечни продукти"),
    ("Млечни десерти", "Млечни продукти"),
    ("Прясно месо", "Месо, риба и колбаси"),
    ("Птиче месо", "Месо, риба и колбаси"),
    ("Риба и морски дарове", "Месо, риба и колбаси"),
    ("Колбаси и наденица", "Месо, риба и колбаси"),
    ("Готови месни продукти", "Месо, риба и колбаси"),
    ("Плодове", "Плодове и зеленчуци"),
    ("Зеленчуци", "Плодове и зеленчуци"),
    ("Гъби и маслини", "Плодове и зеленчуци"),
    ("Хляб и питки", "Хляб, тестени и зърнени"),
    ("Тестени изделия", "Хляб, тестени и зърнени"),
    ("Брашно и зърнени", "Хляб, тестени и зърнени"),
    ("Ориз и бобови", "Хляб, тестени и зърнени"),
    ("Шоколад и бонбони", "Сладкиши и снаксове"),
    ("Бисквити и вафли", "Сладкиши и снаксове"),
    ("Торти и кексове", "Сладкиши и снаксове"),
    ("Сладолед", "Сладкиши и снаксове"),
    ("Чипс и солени снаксове", "Сладкиши и снаксове"),
    ("Вода и минерална вода", "Напитки"),
    ("Сокове и безалкохолни", "Напитки"),
    ("Кафе", "Напитки"),
    ("Чай и какао", "Напитки"),
    ("Бира", "Напитки"),
    ("Вино", "Напитки"),
    ("Спиртни напитки", "Напитки"),
    ("Олио и мазнини", "Подправки и консерви"),
    ("Подправки и сосове", "Подправки и консерви"),
    ("Консерви и буркани", "Подправки и консерви"),
    ("Захар, сол и подсладители", "Подправки и консерви"),
    ("Замразени храни", "Подправки и консерви"),
    ("Детски храни", "Специални"),
    ("Диетични и здравословни", "Специални"),
    ("Домашни любимци", "Домашни любимци"),
    ("Почистващи препарати", "Дом и хигиена"),
    ("Хигиенни продукти", "Дом и хигиена"),
    ("Козметика и грижа за тяло", "Дом и хигиена"),
    ("Домакински стоки", "Дом и хигиена"),
    ("Електроника", "Нехранителни стоки"),
    ("Дрехи и обувки", "Нехранителни стоки"),
    ("Спорт и свободно време", "Нехранителни стоки"),
    ("Цветя и растения", "Нехранителни стоки"),
    ("Друго", "Друго"),
]


def _slugify(name: str) -> str:
    """Simple ASCII slug — transliterate Cyrillic via unicode normalization fallback."""
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", name)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    slug = re.sub(r"[-\s]+", "-", value).strip("-")
    # If slug is empty (fully Cyrillic), use the uuid5 hex as fallback
    return slug or _uid(name).replace("-", "")[:16]


def _rows(items: list[Any]) -> None:
    """Insert category rows, skipping duplicates (idempotent)."""
    conn = op.get_bind()
    for row in items:
        conn.execute(
            sa.text(
                """
                INSERT INTO categories (id, name, slug, parent_id, created_at, updated_at)
                VALUES (:id, :name, :slug, :parent_id, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            row,
        )


def upgrade() -> None:
    """Insert top-level then sub-categories."""
    # Top-level categories (no parent)
    top_rows = [
        {"id": _uid(name), "name": name, "slug": _slugify(name), "parent_id": None}
        for name in _TOP_CATEGORIES
    ]
    _rows(top_rows)

    # Sub-categories (parent = top-level)
    sub_rows = [
        {
            "id": _uid(name),
            "name": name,
            "slug": _slugify(name),
            "parent_id": _uid(parent),
        }
        for name, parent in _SUB_CATEGORIES
    ]
    _rows(sub_rows)


def downgrade() -> None:
    """Remove all seeded category rows."""
    conn = op.get_bind()
    all_ids = [_uid(name) for name in _TOP_CATEGORIES] + [
        _uid(name) for name, _ in _SUB_CATEGORIES
    ]
    conn.execute(
        sa.text("DELETE FROM categories WHERE id = ANY(:ids)"),
        {"ids": all_ids},
    )
