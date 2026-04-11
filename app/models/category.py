"""Category model with self-referential hierarchy."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.product import Product


class Category(BaseModel):
    """A product category supporting a tree hierarchy via parent_id.

    Attributes:
        name: Display name of the category.
        slug: URL-friendly unique identifier.
        parent_id: FK to the parent category (nullable for root categories).
    """

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id"),
        nullable=True,
    )

    # Self-referential relationships
    parent: Mapped[Category | None] = relationship(
        back_populates="children",
        remote_side="Category.id",
        lazy="selectin",
    )
    children: Mapped[list[Category]] = relationship(
        back_populates="parent",
        lazy="selectin",
    )

    # Products in this category
    products: Mapped[list[Product]] = relationship(  # noqa: F821
        back_populates="category",
        lazy="selectin",
    )
