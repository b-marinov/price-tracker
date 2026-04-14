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

    Looks up the store's ``listing_url`` and ``brochure_url`` from the
    database and runs the appropriate scrapers.  If ``listing_url`` is
    set, runs :class:`~app.scrapers.metro_scraper.MetroProductScraper`.
    If ``brochure_url`` is set, runs
    :class:`~app.scrapers.generic_brochure.GenericBrochureScraper`.
    Both may run for the same store.

    Retries up to 3 times with exponential backoff (60s, 120s, 240s).

    Args:
        self: Celery task instance (bound).
        store_slug: The slug identifying which store to scrape.

    Returns:
        A dict with keys: store_slug, status, items_found.

    Raises:
        ValueError: If the store is not found or has no scrape URL configured.
    """

    async def _execute(task_id: str) -> dict[str, Any]:
        from sqlalchemy import select

        from app.database import get_session_factory
        from app.models.scrape_run import ScrapeRun, ScrapeStatus
        from app.models.store import Store
        from app.scrapers.cancel import ScraperCancelled, clear_cancel, make_cancel_checker
        from app.scrapers.generic_brochure import GenericBrochureScraper
        from app.scrapers.base import ScrapedItem
        from app.scrapers.metro_scraper import MetroProductScraper
        from app.scrapers.pipeline import process_scrape

        session_factory = get_session_factory()

        async with session_factory() as db:
            # Resolve store
            result = await db.execute(
                select(Store).where(Store.slug == store_slug)
            )
            store = result.scalar_one_or_none()
            if store is None:
                raise ValueError(f"Store not found: {store_slug!r}")
            if not store.brochure_url and not store.listing_url:
                raise ValueError(
                    f"Store {store_slug!r} has no brochure_url or listing_url "
                    "configured. Set it via the admin panel or directly in "
                    "the stores table."
                )

            # Create ScrapeRun record early so the task_id is persisted
            scrape_run = ScrapeRun(
                store_id=store.id,
                status=ScrapeStatus.RUNNING,
                task_id=task_id,
            )
            db.add(scrape_run)
            await db.commit()
            await db.refresh(scrape_run)

            # Build a cancel checker using the same Redis client attached to this task
            check_cancel = make_cancel_checker(_redis_client, store_slug)

            try:
                all_items: list[ScrapedItem] = []

                # Run listing scraper if configured (e.g. Metro)
                if store.listing_url:
                    check_cancel()
                    listing_scraper = MetroProductScraper(
                        store_slug=store_slug,
                        listing_url=store.listing_url,
                        cancel_checker=check_cancel,
                    )
                    listing_items = await listing_scraper.run()
                    all_items.extend(listing_items)
                    logger.info(
                        "%s: listing scraper returned %d item(s)",
                        store_slug, len(listing_items),
                    )

                # Run brochure scraper if configured
                if store.brochure_url:
                    check_cancel()
                    brochure_scraper = GenericBrochureScraper(
                        store_slug=store_slug,
                        brochure_listing_url=store.brochure_url,
                        cancel_checker=check_cancel,
                    )
                    brochure_items = await brochure_scraper.run()
                    all_items.extend(brochure_items)
                    logger.info(
                        "%s: brochure scraper returned %d item(s)",
                        store_slug, len(brochure_items),
                    )

                check_cancel()
                count = await process_scrape(store_slug, all_items, db)

                scrape_run.status = ScrapeStatus.COMPLETED
                scrape_run.items_found = count
                scrape_run.finished_at = datetime.now(UTC)
                await db.commit()

                if count == 0:
                    logger.error(
                        "SCRAPE ALERT — %s completed but returned 0 items. "
                        "Check Ollama availability and brochure URL. "
                        "Run at: %s",
                        store_slug,
                        scrape_run.finished_at.isoformat(),
                    )
                else:
                    logger.info(
                        "Scraper %s completed — %d new prices", store_slug, count
                    )
                return {
                    "store_slug": store_slug,
                    "status": "completed",
                    "items_found": count,
                }

            except ScraperCancelled:
                scrape_run.status = ScrapeStatus.CANCELLED
                scrape_run.finished_at = datetime.now(UTC)
                await db.commit()
                clear_cancel(_redis_client, store_slug)
                logger.info("Scraper %s was cancelled", store_slug)
                return {
                    "store_slug": store_slug,
                    "status": "cancelled",
                    "items_found": 0,
                }

            except Exception as exc:
                scrape_run.status = ScrapeStatus.FAILED
                scrape_run.error_msg = str(exc)[:2000]
                scrape_run.finished_at = datetime.now(UTC)
                await db.commit()
                raise exc

    # Attach Redis log handler so scraper progress streams to the admin panel
    import redis as _redis_lib
    from app.config import get_settings as _get_settings
    from app.scrapers.redis_log import RedisLogHandler as _RedisLogHandler

    _settings = _get_settings()
    _redis_client = _redis_lib.from_url(_settings.REDIS_URL)
    _redis_handler = _RedisLogHandler(_redis_client, store_slug)
    _redis_handler.setFormatter(logging.Formatter("%(message)s"))
    _redis_handler.setLevel(logging.INFO)
    _scraper_loggers = [
        logging.getLogger("app.scrapers"),
        logging.getLogger("app.scrapers.tasks"),
        logging.getLogger("app.scrapers.llm_parser"),
        logging.getLogger("app.scrapers.pipeline"),
        logging.getLogger("app.scrapers.generic_brochure"),
        logging.getLogger("app.scrapers.metro_scraper"),
    ]
    for _lg in _scraper_loggers:
        _lg.addHandler(_redis_handler)

    try:
        return _run_async(_execute(self.request.id or ""))  # type: ignore[no-any-return]
    except Exception as exc:
        from app.scrapers.cancel import ScraperCancelled as _ScraperCancelled
        if isinstance(exc, _ScraperCancelled):
            return {"store_slug": store_slug, "status": "cancelled", "items_found": 0}
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
    finally:
        for _lg in _scraper_loggers:
            _lg.removeHandler(_redis_handler)
        _redis_client.close()


@celery_app.task  # type: ignore[untyped-decorator]
def run_all_scrapers() -> dict[str, Any]:
    """Trigger individual scraper tasks for every active store with a scrape source.

    Queries the database for active stores that have a brochure_url or
    listing_url configured and fires off a :func:`run_scraper` subtask
    for each one.

    Returns:
        A dict mapping store slugs to "dispatched".
    """

    async def _dispatch() -> dict[str, Any]:
        from sqlalchemy import or_, select

        from app.database import get_session_factory
        from app.models.store import Store

        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(Store.slug).where(
                    Store.active.is_(True),
                    or_(
                        Store.brochure_url.is_not(None),
                        Store.listing_url.is_not(None),
                    ),
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
            import playwright.async_api  # noqa: F401
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


@celery_app.task  # type: ignore[untyped-decorator]
def merge_duplicate_products() -> dict[str, Any]:
    """LLM-powered product deduplication — runs daily after scraping.

    Finds all products with fuzzy-similar names, asks Ollama to determine
    whether each pair represents the same real-world item, and automatically
    merges confirmed duplicates.  No human approval is required.

    Merge logic (see :mod:`app.scrapers.product_merger`):
    - Price records of the dropped product are reassigned to the kept product.
    - The kept product's name and brand are updated to the LLM-chosen canonical
      values.
    - The dropped product row is deleted.

    Returns:
        Dict with keys ``candidates``, ``merged``, ``skipped``.
    """

    async def _run() -> dict[str, Any]:
        from app.config import get_settings
        from app.database import get_session_factory
        from app.scrapers.llm_parser import OllamaVisionClient
        from app.scrapers.product_merger import run_merge_pass

        settings = get_settings()
        llm = OllamaVisionClient(
            host=settings.LLM_OLLAMA_HOST,
            model=settings.LLM_MODEL,
            temperature=0.0,          # deterministic for dedup decisions
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )

        if not llm.is_available():
            logger.error("merge_duplicate_products: Ollama not available — skipping")
            return {"candidates": 0, "merged": 0, "skipped": 0, "error": "Ollama unavailable"}

        session_factory = get_session_factory()
        async with session_factory() as db:
            stats = await run_merge_pass(db, llm)

        logger.info("Product deduplication complete: %s", stats)
        return stats

    return _run_async(_run())
