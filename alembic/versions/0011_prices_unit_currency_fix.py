"""Add unit/pack_info to prices and normalize currency to EUR

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-12

Two changes:
1. Add nullable `unit` (VARCHAR 20) and `pack_info` (VARCHAR 100) columns
   to the prices table so the LLM-extracted unit info is persisted.
2. Normalize any non-EUR currency values (ЛВ, BGN) to EUR — Bulgaria
   adopted the Euro in January 2025, so all prices are EUR going forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prices", sa.Column("unit", sa.String(20), nullable=True))
    op.add_column("prices", sa.Column("pack_info", sa.String(100), nullable=True))

    # Normalize legacy currency codes to EUR
    op.execute("UPDATE prices SET currency = 'EUR' WHERE currency != 'EUR'")


def downgrade() -> None:
    op.drop_column("prices", "pack_info")
    op.drop_column("prices", "unit")
