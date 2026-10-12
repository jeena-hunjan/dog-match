"""FastAPI application and routes."""

from fastapi import FastAPI

from app.schemas import HealthResponse

app = FastAPI(title="Dog Match", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check. `model_loaded` stays False until the vision model is wired in."""
    return HealthResponse(status="ok", model_loaded=False)
