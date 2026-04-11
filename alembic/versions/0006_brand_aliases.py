"""create brand_aliases table with seed data

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-10

"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Seed rows: (alias, canonical)
_SEED_DATA: list[tuple[str, str]] = [
    ("nestle", "Nestlé"),
    ("nestlé", "Nestlé"),
    ("нестле", "Nestlé"),
    ("kaufland", "Kaufland"),
    ("billa", "Billa"),
    ("lidl", "Lidl"),
    ("milka", "Milka"),
    ("ariel", "Ariel"),
    ("nivea", "NIVEA"),
    ("pampers", "Pampers"),
    ("coca-cola", "Coca-Cola"),
    ("pepsi", "Pepsi"),
    ("lay's", "Lay's"),
    ("lays", "Lay's"),
    ("pringles", "Pringles"),
    ("felix", "Felix"),
    ("whiskas", "Whiskas"),
    ("activia", "Activia"),
    ("danone", "Danone"),
    ("president", "Président"),
]


def upgrade() -> None:
    """Create the brand_aliases table and insert seed alias rows."""
    op.create_table(
        "brand_aliases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column("canonical", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias", name="uq_brand_aliases_alias"),
    )
    op.create_index("ix_brand_aliases_alias", "brand_aliases", ["alias"])
    op.create_index("ix_brand_aliases_canonical", "brand_aliases", ["canonical"])

    for alias, canonical in _SEED_DATA:
        op.execute(
            sa.text(
                "INSERT INTO brand_aliases (id, alias, canonical) "
                "VALUES (gen_random_uuid(), :alias, :canonical)"
            ).bindparams(alias=alias, canonical=canonical)
        )


def downgrade() -> None:
    """Drop the brand_aliases table."""
    op.drop_index("ix_brand_aliases_canonical", table_name="brand_aliases")
    op.drop_index("ix_brand_aliases_alias", table_name="brand_aliases")
    op.drop_table("brand_aliases")
