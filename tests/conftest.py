"""Shared pytest fixtures."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

# Set test environment variables before importing app modules.
#
# DATABASE_URL / REDIS_URL use setdefault because the docker-compose
# api container provides container-network URLs (postgres:5432 vs
# localhost:5432) that we must not overwrite when pytest runs inside
# the container.  When running tests outside docker, the localhost
# defaults below kick in.
#
# APP_ENV / ADMIN_KEY / SECRET_KEY ARE force-set: these were
# previously setdefault, but `.env.compose` pre-populates them with
# development values and that leaked into tests — breaking the health
# check (env=development not testing) and the admin auth tests
# (ADMIN_KEY=dev-admin-key not test-admin-key, so requests came back
# 403 instead of the expected 404/500).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/price_tracker_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ["APP_ENV"] = "testing"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_KEY"] = "test-admin-key"

from app.main import app  # noqa: E402


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client.

    Yields:
        AsyncClient: An httpx async client bound to the FastAPI app.
    """
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
