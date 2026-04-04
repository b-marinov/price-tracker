"""Health check router."""

from typing import Any

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Return application health status.

    Returns:
        A dict with status and current environment name.
    """
    settings = get_settings()
    return {"status": "ok", "env": settings.APP_ENV}
