"""Add additional_info to products for specs and dimensions

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-14

Stores free-text product specifications extracted by the LLM that don't
fit into name / brand / pack_info — e.g. dimensions ("42 x 29 x 4 cm"),
technical specs ("20 V, безжична, без батерия и зарядно"), or conditions
("с карта KAUFLAND").
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("additional_info", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "additional_info")
