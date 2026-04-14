"""Redis-based scraper cancellation utilities.

A lightweight cancel flag is written to Redis when the operator requests
a stop.  Scrapers check this flag between pages / scroll rounds and raise
:exc:`ScraperCancelled` as soon as they notice it, allowing the Celery task
to cleanly mark the run as cancelled and exit.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CANCEL_KEY_PREFIX = "scraper:cancel:"
_CANCEL_TTL_SECONDS = 3600  # auto-expire after 1 hour in case of orphaned flags


class ScraperCancelled(Exception):
    """Raised inside a scraper when a cancellation flag is detected."""


def cancel_key(store_slug: str) -> str:
    """Return the Redis key used for the cancel flag of a store.

    Args:
        store_slug: The store slug (e.g. ``"kaufland"``).

    Returns:
        Redis key string.
    """
    return f"{_CANCEL_KEY_PREFIX}{store_slug}"


def request_cancel(redis_client: object, store_slug: str) -> None:
    """Set the cancellation flag for a store scraper.

    Args:
        redis_client: A synchronous ``redis.Redis`` client.
        store_slug: The store whose scraper should be cancelled.
    """
    key = cancel_key(store_slug)
    redis_client.set(key, "1", ex=_CANCEL_TTL_SECONDS)  # type: ignore[attr-defined]
    logger.info("Cancel flag set for store: %s", store_slug)


def clear_cancel(redis_client: object, store_slug: str) -> None:
    """Remove the cancellation flag for a store.

    Args:
        redis_client: A synchronous ``redis.Redis`` client.
        store_slug: The store whose cancel flag to remove.
    """
    redis_client.delete(cancel_key(store_slug))  # type: ignore[attr-defined]


def is_cancelled(redis_client: object, store_slug: str) -> bool:
    """Return True if a cancellation has been requested for the store.

    Args:
        redis_client: A synchronous ``redis.Redis`` client.
        store_slug: The store to check.

    Returns:
        ``True`` if the cancel flag is set, ``False`` otherwise.
    """
    return bool(redis_client.exists(cancel_key(store_slug)))  # type: ignore[attr-defined]


async def async_is_cancelled(redis_client: object, store_slug: str) -> bool:
    """Async version of :func:`is_cancelled` for use inside coroutines.

    Args:
        redis_client: An async ``redis.asyncio.Redis`` client.
        store_slug: The store to check.

    Returns:
        ``True`` if the cancel flag is set, ``False`` otherwise.
    """
    return bool(await redis_client.exists(cancel_key(store_slug)))  # type: ignore[attr-defined]


def make_cancel_checker(redis_client: object, store_slug: str):
    """Return a zero-argument callable that raises :exc:`ScraperCancelled` if flagged.

    Intended for use inside scrapers:

    .. code-block:: python

        check_cancel = make_cancel_checker(redis_client, store_slug)
        for page in pages:
            check_cancel()
            process(page)

    Args:
        redis_client: A synchronous ``redis.Redis`` client.
        store_slug: The store to watch.

    Returns:
        Callable that raises :exc:`ScraperCancelled` when the flag is set.
    """
    def _check() -> None:
        if is_cancelled(redis_client, store_slug):
            logger.info("Cancellation detected for %s — stopping scraper", store_slug)
            raise ScraperCancelled(f"Scraper cancelled for store: {store_slug}")

    return _check
