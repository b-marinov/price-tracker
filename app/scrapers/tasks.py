"""Celery tasks for running scrapers and processing results."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.scrapers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Registry mapping store_slug -> BaseScraper subclass.
# Concrete scrapers register themselves at import time via ``register_scraper``.
_SCRAPER_REGISTRY: dict[str, type] = {}

# --- Eager imports to populate the registry at module load time ---
from app.scrapers.kaufland import KauflandScraper  # noqa: E402
from app.scrapers.billa import BillaScraper  # noqa: E402

_SCRAPER_REGISTRY["kaufland"] = KauflandScraper
_SCRAPER_REGISTRY["billa"] = BillaScraper


def register_scraper(scraper_cls: type) -> type:
    """Register a BaseScraper subclass by its store_slug.

    This decorator should be applied to every concrete scraper class so
    that :func:`run_scraper` can look it up by slug.

    Args:
        scraper_cls: A concrete subclass of BaseScraper.

    Returns:
        The unmodified class (allows use as a decorator).
    """
    _SCRAPER_REGISTRY[scraper_cls.store_slug] = scraper_cls
    return scraper_cls


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous Celery task context.

    Creates a new event loop if none is running.

    Args:
        coro: An awaitable coroutine.

    Returns:
        The result of the coroutine.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Unlikely in Celery worker, but fall back to new loop
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    else:
        return asyncio.run(coro)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_scraper(self: Any, store_slug: str) -> dict:
    """Run a single store scraper: fetch, parse, normalise, upsert.

    Creates a ScrapeRun record at start and updates it on completion
    (success or failure). Retries up to 3 times with exponential backoff
    (60s, 120s, 240s). After max retries the ScrapeRun is marked as failed.

    Args:
        self: Celery task instance (bound).
        store_slug: The slug identifying which scraper to run.

    Returns:
        A dict with keys: store_slug, status, items_found.

    Raises:
        ValueError: If no scraper is registered for the given slug.
    """

    async def _execute() -> dict:
        from app.database import get_session_factory
        from app.models.scrape_run import ScrapeRun, ScrapeStatus
        from app.scrapers.pipeline import process_scrape

        scraper_cls = _SCRAPER_REGISTRY.get(store_slug)
        if scraper_cls is None:
            raise ValueError(
                f"No scraper registered for store_slug={store_slug!r}. "
                f"Available: {list(_SCRAPER_REGISTRY.keys())}"
            )

        session_factory = get_session_factory()

        async with session_factory() as db:
            # Create ScrapeRun record
            scrape_run = ScrapeRun(
                store_id=(
                    await _resolve_store_id(db, store_slug)
                ),
                status=ScrapeStatus.RUNNING,
            )
            db.add(scrape_run)
            await db.commit()
            await db.refresh(scrape_run)

            try:
                scraper = scraper_cls()
                items = await scraper.run()
                count = await process_scrape(store_slug, items, db)

                # Mark success
                scrape_run.status = ScrapeStatus.COMPLETED
                scrape_run.items_found = count
                scrape_run.finished_at = datetime.now(timezone.utc)
                await db.commit()

                logger.info(
                    "Scraper %s completed — %d new prices", store_slug, count
                )
                return {
                    "store_slug": store_slug,
                    "status": "completed",
                    "items_found": count,
                }

            except Exception as exc:
                # Mark failed
                scrape_run.status = ScrapeStatus.FAILED
                scrape_run.error_msg = str(exc)[:2000]
                scrape_run.finished_at = datetime.now(timezone.utc)
                await db.commit()
                raise exc

    try:
        return _run_async(_execute())
    except Exception as exc:
        # Exponential backoff: 60, 120, 240
        countdown = 60 * (2 ** self.request.retries)
        logger.warning(
            "Scraper %s failed (attempt %d/%d): %s — retrying in %ds",
            store_slug,
            self.request.retries + 1,
            self.max_retries + 1,
            exc,
            countdown,
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(
                "Scraper %s permanently failed after %d retries: %s",
                store_slug,
                self.max_retries,
                exc,
            )
            return {
                "store_slug": store_slug,
                "status": "failed",
                "error": str(exc)[:500],
            }


async def _resolve_store_id(db: Any, store_slug: str) -> Any:
    """Look up a store's UUID by slug.

    Args:
        db: An async database session.
        store_slug: The store's unique slug.

    Returns:
        The store's UUID primary key.

    Raises:
        ValueError: If the store is not found.
    """
    from sqlalchemy import select

    from app.models.store import Store

    result = await db.execute(
        select(Store.id).where(Store.slug == store_slug)
    )
    store_id = result.scalars().first()
    if store_id is None:
        raise ValueError(f"Store not found: {store_slug!r}")
    return store_id


@celery_app.task
def run_all_scrapers() -> dict:
    """Trigger individual scraper tasks for every active store.

    Queries the database for active stores and fires off a
    :func:`run_scraper` subtask for each one.

    Returns:
        A dict mapping store slugs to "dispatched".
    """

    async def _dispatch() -> dict:
        from sqlalchemy import select

        from app.database import get_session_factory
        from app.models.store import Store

        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Store.slug).where(Store.active.is_(True))
            )
            slugs = list(result.scalars().all())

        dispatched = {}
        for slug in slugs:
            run_scraper.delay(slug)
            dispatched[slug] = "dispatched"
            logger.info("Dispatched scraper task for store: %s", slug)

        return dispatched

    return _run_async(_dispatch())
