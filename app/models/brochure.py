"""Brochure model representing a store's weekly/promotional PDF flyer."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.store import Store


class Brochure(BaseModel):
    """A PDF brochure published by a store for a promotional period.

    Attributes:
        store_id: FK to the store that published this brochure.
        title: Human-readable title (e.g. "Kaufland — 07–13 Apr 2026").
        pdf_url: Public URL to the PDF file.
        valid_from: First day the brochure offers are valid.
        valid_to: Last day the brochure offers are valid.
        is_current: Whether this is the store's currently active brochure.
    """

    __tablename__ = "brochures"

    store_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    pdf_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, index=True
    )

    # Relationships
    store: Mapped[Store] = relationship(lazy="selectin")
