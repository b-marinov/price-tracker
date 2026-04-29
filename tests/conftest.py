"""Shared pytest fixtures."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

# Set test environment variables before importing app modules.  Force-set
# rather than setdefault — when pytest runs inside the docker-compose api
# container, APP_ENV / DATABASE_URL etc. are pre-populated from
# .env.compose with development values, and a setdefault would leak the
# dev environment into tests (e.g. APP_ENV=development breaking the
# health check assertion).  We always want a deterministic test env.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/price_tracker_test",
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")
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
