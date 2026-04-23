"""Redis-based scraper cancellation, locking, heartbeat, and progress utilities.

A lightweight cancel flag is written to Redis when the operator requests
a stop.  Scrapers check this flag between pages / scroll rounds and raise
:exc:`ScraperCancelled` as soon as they notice it, allowing the Celery task
to cleanly mark the run as cancelled and exit.
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# ── Cancel ────────────────────────────────────────────────────────────────────

_CANCEL_KEY_PREFIX = "scraper:cancel:"
_CANCEL_TTL_SECONDS = 3600


class ScraperCancelled(Exception):
    """Raised inside a scraper when a cancellation flag is detected."""


def cancel_key(store_slug: str) -> str:
    """Return the Redis key used for the cancel flag of a store."""
    return f"{_CANCEL_KEY_PREFIX}{store_slug}"


def request_cancel(redis_client: object, store_slug: str) -> None:
    """Set the cancellation flag for a store scraper."""
    key = cancel_key(store_slug)
    redis_client.set(key, "1", ex=_CANCEL_TTL_SECONDS)  # type: ignore[attr-defined]
    logger.info("Cancel flag set for store: %s", store_slug)


def clear_cancel(redis_client: object, store_slug: str) -> None:
    """Remove the cancellation flag for a store."""
    redis_client.delete(cancel_key(store_slug))  # type: ignore[attr-defined]


def is_cancelled(redis_client: object, store_slug: str) -> bool:
    """Return True if a cancellation has been requested for the store."""
    return bool(redis_client.exists(cancel_key(store_slug)))  # type: ignore[attr-defined]


async def async_is_cancelled(redis_client: object, store_slug: str) -> bool:
    """Async version of :func:`is_cancelled` for use inside coroutines."""
    return bool(await redis_client.exists(cancel_key(store_slug)))  # type: ignore[attr-defined]


def make_cancel_checker(redis_client: object, store_slug: str):
    """Return a callable that raises :exc:`ScraperCancelled` if flagged.

    Also refreshes the heartbeat on each call so the run is known to be alive.
    """
    def _check() -> None:
        if is_cancelled(redis_client, store_slug):
            logger.info("Cancellation detected for %s — stopping scraper", store_slug)
            raise ScraperCancelled(f"Scraper cancelled for store: {store_slug}")
        touch_heartbeat(redis_client, store_slug)

    return _check


# ── Heartbeat ─────────────────────────────────────────────────────────────────

_HEARTBEAT_KEY_PREFIX = "scraper:heartbeat:"
_HEARTBEAT_TTL_SECONDS = 90


def touch_heartbeat(redis_client: object, store_slug: str) -> None:
    """Refresh the heartbeat key proving the scraper is alive."""
    try:
        redis_client.set(  # type: ignore[attr-defined]
            f"{_HEARTBEAT_KEY_PREFIX}{store_slug}", "1", ex=_HEARTBEAT_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        pass  # heartbeat is best-effort


def has_heartbeat(redis_client: object, store_slug: str) -> bool:
    """Return True if a heartbeat exists for the store scraper."""
    try:
        return bool(redis_client.exists(f"{_HEARTBEAT_KEY_PREFIX}{store_slug}"))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def clear_heartbeat(redis_client: object, store_slug: str) -> None:
    """Remove heartbeat key when a scraper finishes."""
    try:
        redis_client.delete(f"{_HEARTBEAT_KEY_PREFIX}{store_slug}")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


# ── Distributed Lock ──────────────────────────────────────────────────────────

_LOCK_KEY_PREFIX = "scraper:lock:"
_LOCK_TTL_SECONDS = 7200  # 2 hours safety cap


def acquire_lock(redis_client: object, store_slug: str) -> bool:
    """Try to acquire an exclusive lock for a store scraper.

    Returns True if acquired, False if already locked.
    """
    try:
        result = redis_client.set(  # type: ignore[attr-defined]
            f"{_LOCK_KEY_PREFIX}{store_slug}", "1", nx=True, ex=_LOCK_TTL_SECONDS,
        )
        return bool(result)
    except Exception:  # noqa: BLE001
        return True  # fail open — let scraper run if Redis is down


def release_lock(redis_client: object, store_slug: str) -> None:
    """Release the exclusive lock for a store scraper."""
    try:
        redis_client.delete(f"{_LOCK_KEY_PREFIX}{store_slug}")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def clear_all_locks(redis_client: object) -> None:
    """Clear all scraper locks (used on worker startup)."""
    try:
        keys = redis_client.keys(f"{_LOCK_KEY_PREFIX}*")  # type: ignore[attr-defined]
        if keys:
            redis_client.delete(*keys)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


# ── Progress ──────────────────────────────────────────────────────────────────

_PROGRESS_KEY_PREFIX = "scraper:progress:"
_PROGRESS_TTL_SECONDS = 7200


def set_progress(
    redis_client: object,
    store_slug: str,
    *,
    step: str,
    page_current: int | None = None,
    page_total: int | None = None,
    items_so_far: int | None = None,
) -> None:
    """Update structured progress for a running scraper."""
    try:
        data = {
            "step": step,
            "page_current": page_current,
            "page_total": page_total,
            "items_so_far": items_so_far,
            "updated_at": time.time(),
        }
        redis_client.set(  # type: ignore[attr-defined]
            f"{_PROGRESS_KEY_PREFIX}{store_slug}",
            json.dumps(data),
            ex=_PROGRESS_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001
        pass


def get_progress(redis_client: object, store_slug: str) -> dict | None:
    """Read the current progress for a store scraper."""
    try:
        raw = redis_client.get(f"{_PROGRESS_KEY_PREFIX}{store_slug}")  # type: ignore[attr-defined]
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    return None


def clear_progress(redis_client: object, store_slug: str) -> None:
    """Remove progress data when a scraper finishes."""
    try:
        redis_client.delete(f"{_PROGRESS_KEY_PREFIX}{store_slug}")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


# ── Schedule Toggle ───────────────────────────────────────────────────────────

_SCHEDULE_KEY = "scraper:schedule_enabled"


def is_schedule_enabled(redis_client: object) -> bool:
    """Return True if the automatic scraper schedule is enabled (default: True)."""
    try:
        val = redis_client.get(_SCHEDULE_KEY)  # type: ignore[attr-defined]
        if val is None:
            return True  # enabled by default
        return val != b"0" and val != "0"
    except Exception:  # noqa: BLE001
        return True


def set_schedule_enabled(redis_client: object, enabled: bool) -> None:
    """Enable or disable the automatic scraper schedule."""
    try:
        redis_client.set(_SCHEDULE_KEY, "1" if enabled else "0")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
