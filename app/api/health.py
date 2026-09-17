from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.version import get_version
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Liveness endpoint; it performs no external or destructive operation."""
    return HealthResponse(
        status="ok",
        service="aso-node-recovery",
        version=get_version(),
        environment=settings.environment,
        dry_run=settings.dry_run,
    )
