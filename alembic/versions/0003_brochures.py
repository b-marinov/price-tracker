"""Add brochures table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the brochures table."""
    op.create_table(
        "brochures",
        sa.Column("id", sa.Uuid(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("store_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("pdf_url", sa.String(2048), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
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
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brochures_store_id", "brochures", ["store_id"])
    op.create_index("ix_brochures_is_current", "brochures", ["is_current"])


def downgrade() -> None:
    """Drop the brochures table."""
    op.drop_index("ix_brochures_is_current", table_name="brochures")
    op.drop_index("ix_brochures_store_id", table_name="brochures")
    op.drop_table("brochures")
