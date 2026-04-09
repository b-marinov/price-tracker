"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return a cached async SQLAlchemy engine.

    Uses ``NullPool`` when running inside a Celery worker or test environment.
    Celery forks workers and each task runs inside ``asyncio.run()``, which
    creates and closes a new event loop per task.  A pooled engine would hold
    connections bound to a previous (closed) loop, causing "Future attached to
    a different loop" errors.  ``NullPool`` gives each task a fresh connection
    with no cross-loop sharing.

    Returns:
        AsyncEngine: The async database engine.
    """
    import os

    settings = get_settings()
    use_null_pool = settings.APP_ENV == "testing" or os.environ.get("CELERY_WORKER") == "1"
    if use_null_pool:
        return create_async_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
        )
    return create_async_engine(
        settings.DATABASE_URL,
        echo=(settings.APP_ENV == "development"),
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory.

    Returns:
        async_sessionmaker: A factory that produces AsyncSession instances.
    """
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session and ensure it is closed.

    Yields:
        AsyncSession: A SQLAlchemy async session.
    """
    async with get_session_factory()() as session:
        yield session
