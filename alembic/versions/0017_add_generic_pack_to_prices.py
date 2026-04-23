"""Add missing generic_pack column to prices table

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-21

Migration 0016 added generic_pack to the products table but assumed it
already existed on prices. The SQLAlchemy model defines it, but the
column was never created — causing 'column prices.generic_pack does not
exist' errors at runtime.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prices", sa.Column("generic_pack", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("prices", "generic_pack")
