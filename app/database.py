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

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Return a cached async SQLAlchemy engine.

    Returns:
        AsyncEngine: The async database engine.
    """
    settings = get_settings()
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
