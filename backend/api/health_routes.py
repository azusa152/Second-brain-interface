from datetime import datetime, timezone

from fastapi import APIRouter

from backend.domain.models import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Health check endpoint")
def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
