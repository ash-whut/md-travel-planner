from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter()


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness check plus the active LLM provider and tool mode (03-contracts §3)."""
    return {
        "ok": True,
        "llm_provider": settings.llm_provider,
        "tool_mode": settings.tool_provider_mode,
    }
