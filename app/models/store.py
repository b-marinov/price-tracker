"""Store model representing a retail store or chain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.price import Price
    from app.models.scrape_run import ScrapeRun


class Store(BaseModel):
    """A retail store or chain whose prices are tracked.

    Attributes:
        name: Display name of the store.
        slug: URL-friendly unique identifier.
        website_url: Store's main website URL.
        logo_url: URL to the store's logo image.
        active: Whether the store is actively being tracked.
    """

    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    brochure_url: Mapped[str | None] = mapped_column(String(2048))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)

    # Relationships
    prices: Mapped[list[Price]] = relationship(  # noqa: F821
        back_populates="store",
        lazy="selectin",
    )
    scrape_runs: Mapped[list[ScrapeRun]] = relationship(  # noqa: F821
        back_populates="store",
        lazy="selectin",
    )
