"""Add unique constraint on prices (product, store, recorded_at)

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-24

The scraper pipeline was creating multiple Price rows for the same
product at the same store within a single scrape run — one per brochure
page on which the product appeared.  This resulted in the product
detail UI showing the same store listed N times with different prices.

Running this migration de-duplicates the prices table (keeping the
lowest price per product+store+recorded_at) and enforces uniqueness
going forward.  Pipeline-side dedup is handled separately.
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM prices a
        USING prices b
        WHERE a.ctid < b.ctid
          AND a.product_id = b.product_id
          AND a.store_id = b.store_id
          AND a.recorded_at = b.recorded_at
        """
    )
    op.create_unique_constraint(
        "prices_product_store_recorded_uniq",
        "prices",
        ["product_id", "store_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "prices_product_store_recorded_uniq",
        "prices",
        type_="unique",
    )
