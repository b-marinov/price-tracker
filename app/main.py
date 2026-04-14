"""FastAPI application entry point."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers.admin import router as admin_router
from app.routers.catalogue import category_router
from app.routers.catalogue import router as catalogue_router
from app.routers.health import router as health_router
from app.routers.products import router as products_router
from app.routers.stores import router as stores_router


MEDIA_DIR = Path(os.getenv("APP_MEDIA_DIR", "/app/media"))
IMAGES_DIR = MEDIA_DIR / "images"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    yield


_settings = get_settings()

app = FastAPI(
    title="Price Tracker",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.CORS_ORIGINS.split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(catalogue_router)
app.include_router(category_router)
app.include_router(health_router)
app.include_router(products_router)
app.include_router(stores_router)

IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
