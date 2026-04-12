"""Add pack_info to products for SKU-level identity

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-12

Products now represent specific SKUs rather than generic types.
pack_info stores the canonical pack size string extracted by the LLM
(e.g. "0.5 л", "1 кг", "6 x 100 г") and is used together with
name + brand as the matching key in the scraper pipeline.

Existing products retain NULL pack_info (unknown/unspecified size).
New scrape runs will create properly keyed product rows going forward.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("pack_info", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "pack_info")
