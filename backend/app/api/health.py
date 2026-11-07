"""GET /api/health: a quick check that the backend is up and which modes it runs in."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter()


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    return {
        "ok": True,
        "llm_provider": settings.llm_provider,
        "tool_mode": settings.tool_provider_mode,
    }
