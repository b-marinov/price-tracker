"""Cascade delete on prices.product_id foreign key.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-29

The Price → Product foreign key was created without ON DELETE CASCADE,
so deleting a Product caused SQLAlchemy to attempt to nullify the FK
on every related Price row.  Because prices.product_id is NOT NULL,
the result was a 500 from any admin product delete with prices
attached (single or batch).

This migration drops the FK and recreates it with ON DELETE CASCADE
so the database mirrors the new ORM cascade and any direct SQL DELETE
also works.
"""

from __future__ import annotations

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


_FK_NAME = "prices_product_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_FK_NAME, "prices", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "prices",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "prices", type_="foreignkey")
    op.create_foreign_key(
        _FK_NAME,
        "prices",
        "products",
        ["product_id"],
        ["id"],
    )
