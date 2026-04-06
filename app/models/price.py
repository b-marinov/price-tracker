"""Price model for tracking product prices over time."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class PriceSource(str, enum.Enum):
    """Source from which the price was obtained."""

    WEB = "web"
    BROCHURE = "brochure"


class Price(BaseModel):
    """A recorded price observation for a product at a store.

    Attributes:
        product_id: FK to the product.
        store_id: FK to the store.
        price: The observed price as a fixed-point decimal.
        currency: ISO 4217 currency code (default BGN).
        recorded_at: UTC timestamp when the price was observed.
        source: How the price was obtained (web scrape or brochure).
    """

    __tablename__ = "prices"
    __table_args__ = (
        Index("ix_prices_product_id", "product_id"),
        Index("ix_prices_store_id", "store_id"),
        Index("ix_prices_recorded_at", "recorded_at"),
        Index(
            "ix_prices_product_store_recorded",
            "product_id",
            "store_id",
            "recorded_at",
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("products.id"),
        nullable=False,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stores.id"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        server_default="BGN",
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    source: Mapped[PriceSource] = mapped_column(
        String(20),
        nullable=False,
    )

    # Relationships
    product: Mapped["Product"] = relationship(  # noqa: F821
        back_populates="prices",
        lazy="selectin",
    )
    store: Mapped["Store"] = relationship(  # noqa: F821
        back_populates="prices",
        lazy="selectin",
    )
