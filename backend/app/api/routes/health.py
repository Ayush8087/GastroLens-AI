from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Report process liveness without depending on external services."""
    return HealthResponse(status="ok")
