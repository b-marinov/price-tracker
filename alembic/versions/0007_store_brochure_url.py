"""add brochure_url to stores table

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_STORE_BROCHURE_URLS = {
    "kaufland":  "https://www.kaufland.bg/broshuri.html",
    "billa":     "https://www.billa.bg/promocii/sedmichna-broshura",
    "lidl":      "https://www.lidl.bg/broshura",
    "fantastico": "https://www.fantastico.bg/special-offers/",
}


def upgrade() -> None:
    """Add brochure_url column to stores and seed known store URLs."""
    op.add_column(
        "stores",
        sa.Column("brochure_url", sa.String(2048), nullable=True),
    )
    for slug, url in _STORE_BROCHURE_URLS.items():
        op.execute(
            sa.text(
                "UPDATE stores SET brochure_url = :url WHERE slug = :slug"
            ).bindparams(url=url, slug=slug)
        )


def downgrade() -> None:
    """Remove brochure_url column from stores."""
    op.drop_column("stores", "brochure_url")
