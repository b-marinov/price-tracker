"""Pydantic response schemas for the price history API."""

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class PricePoint(BaseModel):
    """A single date/price data point.

    Attributes:
        date: The date of the price observation (ISO format YYYY-MM-DD).
        price: The price value as a float.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date
    price: float


class StoreResult(BaseModel):
    """Price history data for a single store.

    Attributes:
        store_id: UUID of the store.
        store_name: Display name of the store.
        data: List of date/price data points.
    """

    model_config = ConfigDict(from_attributes=True)

    store_id: uuid.UUID
    store_name: str
    data: list[PricePoint]


class PriceHistoryResponse(BaseModel):
    """Top-level response for the price history endpoint.

    Attributes:
        product_id: UUID of the product.
        store_results: List of per-store price history data.
    """

    model_config = ConfigDict(from_attributes=True)

    product_id: uuid.UUID
    store_results: list[StoreResult]
