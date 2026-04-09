"""Celery application instance and beat schedule configuration."""

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]
from celery.signals import worker_process_init  # type: ignore[import-untyped]

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
    # Beat schedule
    beat_schedule={
        "run-all-scrapers-daily": {
            "task": "app.scrapers.tasks.run_all_scrapers",
            "schedule": crontab(hour=6, minute=0),  # 06:00 Europe/Sofia
        },
    },
)


@worker_process_init.connect
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
