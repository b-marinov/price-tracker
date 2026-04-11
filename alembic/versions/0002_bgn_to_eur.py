"""Migrate currency from BGN to EUR — BGN decommissioned.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-06

Updates:
- prices.currency server default BGN → EUR
- Backfills all existing rows: SET currency = 'EUR' WHERE currency = 'BGN'
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Change prices.currency default to EUR and migrate existing BGN rows."""
    # Update the column server default
    op.alter_column(
        "prices",
        "currency",
        server_default="EUR",
        existing_type=sa.String(3),
        existing_nullable=False,
    )
    # Backfill all existing BGN prices to EUR
    op.execute("UPDATE prices SET currency = 'EUR' WHERE currency = 'BGN'")


def downgrade() -> None:
    """Revert prices.currency default to BGN (data loss — EUR rows become BGN)."""
    op.alter_column(
        "prices",
        "currency",
        server_default="BGN",
        existing_type=sa.String(3),
        existing_nullable=False,
    )
    op.execute("UPDATE prices SET currency = 'BGN' WHERE currency = 'EUR'")
