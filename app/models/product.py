"""Product model with status enum."""

import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ProductStatus(str, enum.Enum):
    """Status of a product in the system."""

    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"


class Product(BaseModel):
    """A tracked product with its metadata.

    Attributes:
        name: Display name of the product.
        slug: URL-friendly unique identifier.
        brand: Brand or manufacturer name.
        category_id: FK to the product's category.
        image_url: URL to the product image.
        barcode: EAN/UPC barcode string.
        status: Current status (active or pending_review).
    """

    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id"),
        nullable=True,
    )
    image_url: Mapped[str | None] = mapped_column(String(2048))
    barcode: Mapped[str | None] = mapped_column(String(50), index=True)
    status: Mapped[ProductStatus] = mapped_column(
        String(20),
        default=ProductStatus.ACTIVE,
        server_default=ProductStatus.ACTIVE.value,
        nullable=False,
    )

    # Relationships
    category: Mapped["Category | None"] = relationship(  # noqa: F821
        back_populates="products",
        lazy="selectin",
    )
    prices: Mapped[list["Price"]] = relationship(  # noqa: F821
        back_populates="product",
        lazy="selectin",
    )
