"""Scrapers package — BaseScraper, pipeline, and Celery task definitions."""

from app.scrapers.base import BaseScraper, ScrapedItem

__all__ = [
    "BaseScraper",
    "ScrapedItem",
]
