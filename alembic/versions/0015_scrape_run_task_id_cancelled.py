"""Add task_id to scrape_runs and CANCELLED status

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scrape_runs",
        sa.Column("task_id", sa.String(255), nullable=True),
    )
    # The status column is VARCHAR(20) — "cancelled" fits within that limit.
    # No schema change needed for the enum; the new value is accepted by
    # the CHECK-free string column used by SQLAlchemy's StrEnum mapping.


def downgrade() -> None:
    op.drop_column("scrape_runs", "task_id")
