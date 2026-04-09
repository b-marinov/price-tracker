"""Pydantic schemas for store and brochure API responses."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class StoreResponse(BaseModel):
    """A tracked grocery store."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    website_url: str | None = None
    logo_url: str | None = None
    active: bool


class BrochureResponse(BaseModel):
    """A store brochure (PDF flyer) with validity period."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    store_id: uuid.UUID
    store_name: str
    store_slug: str
    title: str
    pdf_url: str
    valid_from: date | None = None
    valid_to: date | None = None
    is_current: bool
    created_at: datetime
