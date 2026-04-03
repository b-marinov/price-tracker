"""Celery application instance and beat schedule configuration."""

from celery import Celery
from celery.schedules import crontab

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
