from fastapi import APIRouter, Request

from ..models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        algorithm_mode="unconfigured",
        service="firex-backend",
        processing_mode=request.app.state.processing_mode,
    )
