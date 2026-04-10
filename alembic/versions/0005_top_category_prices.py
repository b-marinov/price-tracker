"""add top_category column to prices table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-10

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add top_category column and its index to the prices table."""
    op.add_column("prices", sa.Column("top_category", sa.String(100), nullable=True))
    op.create_index("ix_prices_top_category", "prices", ["top_category"])


def downgrade() -> None:
    """Remove the ix_prices_top_category index and top_category column."""
    op.drop_index("ix_prices_top_category", table_name="prices")
    op.drop_column("prices", "top_category")
