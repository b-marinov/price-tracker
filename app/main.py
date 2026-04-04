"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    # Startup: add resource initialization here (e.g. Redis pool)
    yield
    # Shutdown: add cleanup here


app = FastAPI(
    title="Price Tracker",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
