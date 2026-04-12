"""Backfill Product.brand from Price.brand and fix brand-in-name records

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-12

Two-pass data migration:

Pass 1 — fix legacy "brand-in-name" records.
    Before session 11 the LLM stored brand+type together as the product
    name (e.g. "Ferrero Шоколадови Бонбони").  The fix landed 2026-04-11;
    any surviving records are split here.  Detection heuristic: the first
    token is composed entirely of Latin characters / common brand punctuation
    (A-Za-z0-9 . - &) AND the remainder contains at least one Cyrillic
    character.  This catches brands like Milka, Ferrero, Coca-Cola, NESCAFE
    while leaving pure-Cyrillic generic names untouched.

    The operation is idempotent: if the same product is already correctly
    named it won't be touched.

Pass 2 — backfill Product.brand from Price.brand.
    For each product where brand IS NULL, pick the most-frequently-used
    brand string from all related Price rows (mode).  Products with no
    branded prices stay NULL.

    This pass is also idempotent.
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

# Matches a name where the first whitespace-delimited token is a Latin brand
# and the rest contains at least one Cyrillic character.
_BRAND_IN_NAME = re.compile(
    r"^([A-Za-z0-9.\-&]+)\s+(.+)$",
    re.UNICODE,
)
_CYRILLIC = re.compile(r"[\u0400-\u04ff]", re.UNICODE)


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def upgrade() -> None:
    """Backfill Product.brand and fix brand-polluted product names."""
    conn = op.get_bind()

    # ---------- Pass 1 — fix brand-in-name records ----------
    products = conn.execute(
        sa.text(
            "SELECT id, name, brand FROM products WHERE brand IS NULL"
        )
    ).fetchall()

    for row in products:
        product_id, name, brand = row
        if brand is not None:
            continue  # already has brand — skip

        m = _BRAND_IN_NAME.match(name)
        if m and _has_cyrillic(m.group(2)):
            extracted_brand = m.group(1)
            generic_name = m.group(2).strip()
            conn.execute(
                sa.text(
                    "UPDATE products"
                    " SET name = :name, brand = :brand"
                    " WHERE id = :id"
                ),
                {"name": generic_name, "brand": extracted_brand, "id": product_id},
            )

    # ---------- Pass 2 — backfill Product.brand from Price.brand ----------
    # Use mode() aggregate: pick the most common non-NULL brand per product.
    # mode() WITHIN GROUP is standard SQL and supported by PostgreSQL.
    conn.execute(
        sa.text(
            """
            UPDATE products p
            SET brand = sub.modal_brand
            FROM (
                SELECT
                    pr.product_id,
                    mode() WITHIN GROUP (ORDER BY pr.brand) AS modal_brand
                FROM prices pr
                WHERE pr.brand IS NOT NULL
                GROUP BY pr.product_id
            ) sub
            WHERE p.id = sub.product_id
              AND p.brand IS NULL
              AND sub.modal_brand IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    """Clear backfilled brands (sets all Product.brand to NULL).

    Note: this is a lossy downgrade — any brand data that existed before
    this migration ran will also be cleared.
    """
    op.execute(sa.text("UPDATE products SET brand = NULL"))
