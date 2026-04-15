"""Price model for tracking product prices over time."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.store import Store


class PriceSource(enum.StrEnum):
    """Source from which the price was obtained."""

    WEB = "web"
    BROCHURE = "brochure"


class Price(BaseModel):
    """A recorded price observation for a product at a store.

    Attributes:
        product_id: FK to the product.
        store_id: FK to the store.
        price: The observed price as a fixed-point decimal.
        currency: ISO 4217 currency code (default EUR).
        recorded_at: UTC timestamp when the price was observed.
        source: How the price was obtained (web scrape or brochure).
        brand: Brand name extracted by LLM (nullable).
        product_type: Product type extracted by LLM (nullable).
        category: Product category extracted by LLM (nullable, indexed).
        top_category: Top-level category group extracted by LLM (nullable, indexed).
        original_price: Original price before discount (nullable).
        discount_percent: Discount percentage (nullable).
        image_url: URL of the product image (nullable).
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
        server_default="EUR",
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
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True,
    )
    top_category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    generic_pack: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pack_info: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pack_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    discount_percent: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True,
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    product: Mapped[Product] = relationship(  # noqa: F821
        back_populates="prices",
        lazy="selectin",
    )
    store: Mapped[Store] = relationship(  # noqa: F821
        back_populates="prices",
        lazy="selectin",
    )
