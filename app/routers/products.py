"""Product endpoints including price history."""

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.price import Price
from app.models.product import Product
from app.models.store import Store
from app.schemas.history import PriceHistoryResponse, PricePoint, StoreResult

router = APIRouter(prefix="/products", tags=["products"])


class Interval(str, Enum):
    """Supported aggregation intervals for price history."""

    DAILY = "daily"
    WEEKLY = "weekly"


async def _get_product_or_404(
    product_id: uuid.UUID,
    db: AsyncSession,
) -> Product:
    """Fetch a product by ID or raise 404.

    Args:
        product_id: The UUID of the product to look up.
        db: The async database session.

    Returns:
        The Product instance.

    Raises:
        HTTPException: 404 if the product does not exist.
    """
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def _aggregate_weekly(points: list[PricePoint]) -> list[PricePoint]:
    """Aggregate daily price points into weekly averages.

    Groups prices by ISO year and week number, returning the Monday
    of each week as the representative date.

    Args:
        points: Daily price points, assumed sorted by date.

    Returns:
        Weekly-aggregated price points sorted by date.
    """
    if not points:
        return []

    weekly: dict[tuple[int, int], list[float]] = defaultdict(list)
    week_dates: dict[tuple[int, int], date] = {}

    for point in points:
        iso = point.date.isocalendar()
        key = (iso.year, iso.week)
        weekly[key].append(point.price)
        if key not in week_dates:
            week_dates[key] = point.date

    result = []
    for key in sorted(weekly.keys()):
        avg_price = round(sum(weekly[key]) / len(weekly[key]), 2)
        result.append(PricePoint(date=week_dates[key], price=avg_price))

    return result


@router.get("/{product_id}/history", response_model=PriceHistoryResponse)
async def get_price_history(
    product_id: uuid.UUID,
    store_id: uuid.UUID | None = Query(default=None, description="Filter to a single store"),
    from_date: date | None = Query(default=None, description="Start date (inclusive, ISO format)"),
    to_date: date | None = Query(default=None, description="End date (inclusive, ISO format)"),
    interval: Interval = Query(default=Interval.DAILY, description="Aggregation interval"),
    db: AsyncSession = Depends(get_db_session),
) -> PriceHistoryResponse:
    """Return price history for a product, grouped by store.

    Args:
        product_id: UUID of the product.
        store_id: Optional UUID to filter to a single store.
        from_date: Optional start date filter (inclusive).
        to_date: Optional end date filter (inclusive).
        interval: Aggregation interval (daily or weekly).
        db: Async database session (injected).

    Returns:
        PriceHistoryResponse with per-store price data.

    Raises:
        HTTPException: 404 if product not found.
    """
    product = await _get_product_or_404(product_id, db)

    stmt = (
        select(Price, Store.name)
        .join(Store, Price.store_id == Store.id)
        .where(Price.product_id == product.id)
        .order_by(Price.recorded_at.asc())
    )

    if store_id is not None:
        stmt = stmt.where(Price.store_id == store_id)

    if from_date is not None:
        from_dt = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc)
        stmt = stmt.where(Price.recorded_at >= from_dt)

    if to_date is not None:
        to_dt = datetime(
            to_date.year, to_date.month, to_date.day,
            hour=23, minute=59, second=59, microsecond=999999,
            tzinfo=timezone.utc,
        )
        stmt = stmt.where(Price.recorded_at <= to_dt)

    rows = await db.execute(stmt)
    results = rows.all()

    # Group by store
    store_data: dict[uuid.UUID, dict[str, str | list[PricePoint]]] = {}

    for price_obj, store_name in results:
        sid = price_obj.store_id
        if sid not in store_data:
            store_data[sid] = {"store_name": store_name, "points": []}

        recorded_date = price_obj.recorded_at.date()
        point = PricePoint(
            date=recorded_date,
            price=float(price_obj.price),
        )
        store_data[sid]["points"].append(point)  # type: ignore[union-attr]

    # Build response
    store_results: list[StoreResult] = []
    for sid, data in store_data.items():
        points: list[PricePoint] = data["points"]  # type: ignore[assignment]
        if interval == Interval.WEEKLY:
            points = _aggregate_weekly(points)

        store_results.append(
            StoreResult(
                store_id=sid,
                store_name=str(data["store_name"]),
                data=points,
            )
        )

    return PriceHistoryResponse(
        product_id=product.id,
        store_results=store_results,
    )
