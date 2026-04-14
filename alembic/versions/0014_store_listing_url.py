"""Add listing_url to stores for DOM-based product page scrapers

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("listing_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "listing_url")
