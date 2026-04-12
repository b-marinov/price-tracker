"""Celery tasks for running scrapers and processing results."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.scrapers.celery_app import celery_app

logger = logging.getLogger(__name__)


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
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    else:
        return asyncio.run(coro)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_scraper(self: Any, store_slug: str) -> dict[str, Any]:
    """Run a single store scraper: fetch, parse, normalise, upsert.

    Looks up the store's ``brochure_url`` from the database and runs the
    :class:`~app.scrapers.generic_brochure.GenericBrochureScraper`.
    Retries up to 3 times with exponential backoff (60s, 120s, 240s).

    Args:
        self: Celery task instance (bound).
        store_slug: The slug identifying which store to scrape.

    Returns:
        A dict with keys: store_slug, status, items_found.

    Raises:
        ValueError: If the store is not found or has no brochure_url.
    """

    async def _execute() -> dict[str, Any]:
        from sqlalchemy import select

        from app.database import get_session_factory
        from app.models.scrape_run import ScrapeRun, ScrapeStatus
        from app.models.store import Store
        from app.scrapers.generic_brochure import GenericBrochureScraper
        from app.scrapers.pipeline import process_scrape

        session_factory = get_session_factory()

        async with session_factory() as db:
            # Resolve store + brochure URL
            result = await db.execute(
                select(Store).where(Store.slug == store_slug)
            )
            store = result.scalar_one_or_none()
            if store is None:
                raise ValueError(f"Store not found: {store_slug!r}")
            if not store.brochure_url:
                raise ValueError(
                    f"Store {store_slug!r} has no brochure_url configured. "
                    "Set it via the admin panel or directly in the stores table."
                )

            scraper = GenericBrochureScraper(
                store_slug=store_slug,
                brochure_listing_url=store.brochure_url,
            )

            # Create ScrapeRun record
            scrape_run = ScrapeRun(
                store_id=store.id,
                status=ScrapeStatus.RUNNING,
            )
            db.add(scrape_run)
            await db.commit()
            await db.refresh(scrape_run)

            try:
                items = await scraper.run()
                count = await process_scrape(store_slug, items, db)

                scrape_run.status = ScrapeStatus.COMPLETED
                scrape_run.items_found = count
                scrape_run.finished_at = datetime.now(UTC)
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
                scrape_run.status = ScrapeStatus.FAILED
                scrape_run.error_msg = str(exc)[:2000]
                scrape_run.finished_at = datetime.now(UTC)
                await db.commit()
                raise exc

    try:
        return _run_async(_execute())  # type: ignore[no-any-return]
    except Exception as exc:
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


@celery_app.task  # type: ignore[untyped-decorator]
def run_all_scrapers() -> dict[str, Any]:
    """Trigger individual scraper tasks for every active store with a brochure_url.

    Queries the database for active stores that have a brochure_url configured
    and fires off a :func:`run_scraper` subtask for each one.

    Returns:
        A dict mapping store slugs to "dispatched".
    """

    async def _dispatch() -> dict[str, Any]:
        from sqlalchemy import select

        from app.database import get_session_factory
        from app.models.store import Store

        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Store.slug).where(
                    Store.active.is_(True),
                    Store.brochure_url.is_not(None),
                )
            )
            slugs = list(result.scalars().all())

        dispatched = {}
        for slug in slugs:
            run_scraper.delay(slug)
            dispatched[slug] = "dispatched"
            logger.info("Dispatched scraper task for store: %s", slug)

        return dispatched

    return _run_async(_dispatch())


@celery_app.task
def verify_scraper_health(store_slug: str) -> dict[str, Any]:
    """Run health checks on a scraper to help diagnose issues.

    This task performs:
    1. Check that Playwright is available
    2. Check that Ollama is available
    3. Try to fetch from the store's brochure page
    4. Return detailed diagnostics

    Args:
        store_slug: The store to verify.

    Returns:
        A dict with health check results.
    """

    async def _check() -> dict[str, Any]:
        from sqlalchemy import select

        from app.config import get_settings
        from app.database import get_session_factory
        from app.models.store import Store
        from app.scrapers.generic_brochure import GenericBrochureScraper
        from app.scrapers.llm_parser import OllamaVisionClient

        session_factory = get_session_factory()
        settings = get_settings()
        store = None

        async with session_factory() as db:
            result = await db.execute(
                select(Store).where(Store.slug == store_slug)
            )
            store = result.scalars().first()

        diagnostics = {
            "store_slug": store_slug,
        }

        # Check Playwright
        try:
            from playwright.async_api import async_playwright
            diagnostics["playwright_available"] = True
        except ImportError:
            diagnostics["playwright_available"] = False

        # Check Ollama
        llm = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        diagnostics["ollama_available"] = llm.is_available()
        diagnostics["llm_model"] = settings.LLM_MODEL
        diagnostics["llm_enabled"] = settings.LLM_PARSER_ENABLED

        if not diagnostics["playwright_available"]:
            diagnostics["error"] = "Playwright not installed"
            return diagnostics

        if not diagnostics["ollama_available"]:
            diagnostics["error"] = "Ollama not available"
            return diagnostics

        # Try to fetch
        if not store or not store.brochure_url:
            diagnostics["error"] = "Store not found or no brochure_url"
            return diagnostics

        scraper = GenericBrochureScraper(
            store_slug=store_slug,
            brochure_listing_url=store.brochure_url,
        )

        try:
            result = await scraper.run()
            diagnostics["fetch_success"] = True
            diagnostics["items_found"] = len(result)
            if result:
                diagnostics["sample_items"] = [
                    {"name": r.name, "price": float(r.price)}
                    for r in result[:3]
                ]
            else:
                diagnostics["error"] = "Fetcher returned no items"
        except Exception as exc:
            diagnostics["fetch_success"] = False
            diagnostics["error"] = str(exc)[:500]

        return diagnostics

    return _run_async(_check())  # type: ignore[no-any-return]
