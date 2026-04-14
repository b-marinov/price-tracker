"""Redis-backed log handler for streaming scraper progress to the admin panel."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime


REDIS_LOG_KEY = "scraper:logs"
MAX_LOG_ENTRIES = 500


class RedisLogHandler(logging.Handler):
    """Logging handler that pushes structured records to a Redis list.

    Records are stored as JSON objects with keys: ts, store, level, msg.
    The list is capped at MAX_LOG_ENTRIES using LTRIM.

    Args:
        redis_client: A synchronous redis.Redis instance.
        store_slug: Label injected into every log record.
    """

    def __init__(self, redis_client: object, store_slug: str) -> None:
        super().__init__()
        self._redis = redis_client
        self._store = store_slug

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "store": self._store,
                    "level": record.levelname,
                    "msg": self.format(record),
                }
            )
            self._redis.lpush(REDIS_LOG_KEY, entry)
            self._redis.ltrim(REDIS_LOG_KEY, 0, MAX_LOG_ENTRIES - 1)
        except Exception:  # noqa: BLE001
            pass  # never raise from a log handler
