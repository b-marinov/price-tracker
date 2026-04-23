"""Celery application instance and beat schedule configuration."""

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init, worker_ready

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "price_tracker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone — schedule runs in Europe/Sofia
    timezone="Europe/Sofia",
    enable_utc=True,
    # Task autodiscovery
    include=["app.scrapers.tasks"],
    # Limit to 1 concurrent scraper so Ollama is never hit by two workers at once.
    # LLM inference is GPU-bound; parallel requests cause timeouts.
    worker_concurrency=1,
    # Beat schedule
    beat_schedule={
        "run-all-scrapers-daily": {
            "task": "app.scrapers.tasks.run_all_scrapers",
            "schedule": crontab(hour=6, minute=0),  # 06:00 Europe/Sofia
        },
        "merge-duplicate-products-daily": {
            # Runs 3 h after scraping starts — enough time for all 4 stores to finish
            "task": "app.scrapers.tasks.merge_duplicate_products",
            "schedule": crontab(hour=9, minute=0),  # 09:00 Europe/Sofia
        },
    },
)


@worker_process_init.connect  # type: ignore[untyped-decorator]
def reset_db_engine(**kwargs: object) -> None:
    """Clear the cached SQLAlchemy engine after Celery forks a worker process.

    Each forked worker runs tasks via ``asyncio.run()``, which creates and
    closes a new event loop per task.  Reusing a pooled engine across event
    loop boundaries causes "Future attached to a different loop" errors.
    Clearing the cache here forces a fresh NullPool engine to be created
    inside the worker process, avoiding the stale-loop issue entirely.
    """
    import os

    os.environ["CELERY_WORKER"] = "1"

    from app.database import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()


@worker_ready.connect  # type: ignore[untyped-decorator]
def cleanup_stale_runs(**kwargs: object) -> None:
    """Mark orphaned RUNNING scrape runs as FAILED and clear all locks on startup.

    When a worker crashes or restarts, any in-progress scrape runs are left
    in ``RUNNING`` status forever.  This handler fires once when the worker
    is ready and resets that state so scrapers can be re-dispatched cleanly.
    """
    import asyncio
    import logging

    import redis as _redis_lib

    from app.scrapers.cancel import clear_all_locks

    _logger = logging.getLogger(__name__)

    # Clear all Redis locks so no store is permanently blocked
    _settings = get_settings()
    rc = _redis_lib.from_url(_settings.REDIS_URL)
    try:
        clear_all_locks(rc)
        _logger.info("Worker startup: cleared all scraper locks")
    finally:
        rc.close()

    # Mark stale RUNNING rows as FAILED
    async def _mark_stale() -> None:
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.database import get_session_factory
        from app.models.scrape_run import ScrapeRun, ScrapeStatus

        session_factory = get_session_factory()
        async with session_factory() as db:
            result = await db.execute(
                select(ScrapeRun).where(ScrapeRun.status == ScrapeStatus.RUNNING)
            )
            stale_runs = list(result.scalars().all())
            for run in stale_runs:
                run.status = ScrapeStatus.FAILED
                run.error_msg = "Worker restarted — marked as failed (stale)"
                run.finished_at = datetime.now(UTC)
            if stale_runs:
                await db.commit()
                _logger.info(
                    "Worker startup: marked %d stale RUNNING run(s) as FAILED",
                    len(stale_runs),
                )

    try:
        asyncio.run(_mark_stale())
    except Exception as exc:  # noqa: BLE001
        _logger.warning("Worker startup cleanup failed: %s", exc)
