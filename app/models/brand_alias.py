"""BrandAlias model for normalising brand name variants."""
from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class BrandAlias(BaseModel):
    """Maps a brand name variant to its canonical form.

    Attributes:
        alias: Variant spelling (stored lowercase, stripped).
        canonical: The canonical brand name to display.
    """

    __tablename__ = "brand_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_brand_aliases_alias"),)

    alias: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    canonical: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
