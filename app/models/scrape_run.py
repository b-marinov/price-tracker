"""ScrapeRun model for tracking scraping job executions."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.store import Store


class ScrapeStatus(enum.StrEnum):
    """Status of a scrape run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapeRun(BaseModel):
    """A record of a single scraping job execution.

    Attributes:
        store_id: FK to the store being scraped.
        started_at: UTC timestamp when the run started.
        finished_at: UTC timestamp when the run finished (nullable).
        items_found: Number of price items found during the run.
        status: Current status of the scrape run.
        error_msg: Error message if the run failed.
    """

    __tablename__ = "scrape_runs"

    store_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("stores.id"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    items_found: Mapped[int] = mapped_column(
        Integer,
        server_default="0",
        nullable=False,
    )
    status: Mapped[ScrapeStatus] = mapped_column(
        String(20),
        default=ScrapeStatus.PENDING,
        server_default=ScrapeStatus.PENDING.value,
        nullable=False,
    )
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    store: Mapped[Store] = relationship(  # noqa: F821
        back_populates="scrape_runs",
        lazy="selectin",
    )
