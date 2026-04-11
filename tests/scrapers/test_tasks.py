"""Tests for Celery tasks — run_scraper and run_all_scrapers."""

from __future__ import annotations

from app.scrapers.celery_app import celery_app
from app.scrapers.tasks import _SCRAPER_REGISTRY, register_scraper


class TestRegisterScraper:
    """Tests for the scraper registry decorator."""

    def test_register_scraper_adds_to_registry(self) -> None:
        """register_scraper should add the class to the registry by slug."""

        class DummyScraper:
            store_slug = "dummy"

        register_scraper(DummyScraper)
        assert "dummy" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["dummy"] is DummyScraper

        # Cleanup
        del _SCRAPER_REGISTRY["dummy"]

    def test_register_scraper_returns_class(self) -> None:
        """register_scraper should return the class unchanged (decorator)."""

        class AnotherScraper:
            store_slug = "another"

        result = register_scraper(AnotherScraper)
        assert result is AnotherScraper

        # Cleanup
        del _SCRAPER_REGISTRY["another"]


class TestCeleryAppConfig:
    """Tests for Celery application configuration."""

    def test_beat_schedule_exists(self) -> None:
        """Beat schedule should include the daily run_all_scrapers task."""
        schedule = celery_app.conf.beat_schedule
        assert "run-all-scrapers-daily" in schedule

    def test_beat_schedule_task_name(self) -> None:
        """Beat schedule entry should reference the correct task path."""
        entry = celery_app.conf.beat_schedule["run-all-scrapers-daily"]
        assert entry["task"] == "app.scrapers.tasks.run_all_scrapers"

    def test_beat_schedule_time_is_0600(self) -> None:
        """Beat schedule crontab should fire at 06:00 (hour=6, minute=0)."""
        from celery.schedules import crontab
        entry = celery_app.conf.beat_schedule["run-all-scrapers-daily"]
        schedule = entry["schedule"]
        assert isinstance(schedule, crontab)
        # crontab stores hour/minute as sets of integers
        assert schedule.hour == {6}
        assert schedule.minute == {0}

    def test_timezone_is_sofia(self) -> None:
        """Celery timezone should be set to Europe/Sofia."""
        assert celery_app.conf.timezone == "Europe/Sofia"

    def test_enable_utc(self) -> None:
        """Celery should run with UTC enabled alongside the Sofia schedule."""
        assert celery_app.conf.enable_utc is True

    def test_serializer_is_json(self) -> None:
        """Celery should use JSON serialisation."""
        assert celery_app.conf.task_serializer == "json"

    def test_accept_content_is_json(self) -> None:
        """Celery should only accept JSON content."""
        assert "json" in celery_app.conf.accept_content

    def test_result_serializer_is_json(self) -> None:
        """Celery should serialise results as JSON."""
        assert celery_app.conf.result_serializer == "json"

    def test_tasks_module_included(self) -> None:
        """Celery autodiscovery should include the scrapers tasks module."""
        assert "app.scrapers.tasks" in celery_app.conf.include


class TestRunScraperTask:
    """Tests for the run_scraper Celery task."""

    def test_run_scraper_is_registered(self) -> None:
        """run_scraper should be a registered Celery task."""
        assert "app.scrapers.tasks.run_scraper" in celery_app.tasks

    def test_run_scraper_max_retries(self) -> None:
        """run_scraper should be configured with max_retries=3."""
        task = celery_app.tasks["app.scrapers.tasks.run_scraper"]
        assert task.max_retries == 3

    def test_run_scraper_acks_late(self) -> None:
        """run_scraper should acknowledge messages late for reliability."""
        task = celery_app.tasks["app.scrapers.tasks.run_scraper"]
        assert task.acks_late is True
