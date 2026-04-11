"""add LLM fields to prices table

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-10

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prices", sa.Column("brand", sa.String(200), nullable=True))
    op.add_column("prices", sa.Column("product_type", sa.String(200), nullable=True))
    op.add_column("prices", sa.Column("category", sa.String(100), nullable=True))
    op.add_column("prices", sa.Column("original_price", sa.Numeric(10, 2), nullable=True))
    op.add_column("prices", sa.Column("discount_percent", sa.SmallInteger(), nullable=True))
    op.add_column("prices", sa.Column("image_url", sa.Text(), nullable=True))
    op.create_index("ix_prices_category", "prices", ["category"])


def downgrade() -> None:
    op.drop_index("ix_prices_category", table_name="prices")
    op.drop_column("prices", "image_url")
    op.drop_column("prices", "discount_percent")
    op.drop_column("prices", "original_price")
    op.drop_column("prices", "category")
    op.drop_column("prices", "product_type")
    op.drop_column("prices", "brand")
