"""Add pack_type and generic_pack columns for pack variants

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-15

Products and prices now have separate generic_pack (size/quantity like "1 кг")
and pack_type (material like "кенче", "пакет") columns. This allows products
with the same pack size but different packaging materials to be variants of
the same product family while still being distinct in the database.

The existing pack_info column is kept for backward compatibility as a computed
field (generic_pack + pack_type).

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add generic_pack column to products
    op.add_column("products", sa.Column("generic_pack", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("pack_type", sa.String(50), nullable=True))

    # Add pack_type column to prices (generic_pack already there from pack_info)
    op.add_column("prices", sa.Column("pack_type", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "generic_pack")
    op.drop_column("products", "pack_type")
    op.drop_column("prices", "pack_type")
