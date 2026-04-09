"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.routers.admin import router as admin_router
from app.routers.catalogue import category_router, router as catalogue_router
from app.routers.health import router as health_router
from app.routers.products import router as products_router
from app.routers.stores import router as stores_router


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

app.include_router(admin_router)
app.include_router(catalogue_router)
app.include_router(category_router)
app.include_router(health_router)
app.include_router(products_router)
app.include_router(stores_router)
