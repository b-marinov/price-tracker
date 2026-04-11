"""backfill product.category_id from price.category strings

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-11

For every product where category_id IS NULL, finds the most recent Price row
with a non-null category string, looks up the matching Category by name, and
sets product.category_id. Requires migration 0008 to have run first.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Set product.category_id for products that have price category strings."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE products
            SET category_id = c.id
            FROM (
                SELECT DISTINCT ON (p.product_id)
                    p.product_id,
                    p.category
                FROM prices p
                WHERE p.category IS NOT NULL
                ORDER BY p.product_id, p.recorded_at DESC
            ) latest_price
            JOIN categories c ON c.name = latest_price.category
            WHERE products.id = latest_price.product_id
              AND products.category_id IS NULL
            """
        )
    )


def downgrade() -> None:
    """Cannot safely reverse — would need to know which category_ids were NULL before."""
    pass
