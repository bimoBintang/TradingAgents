"""System endpoints — health check, readiness probe, and engine status."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text

from api.schemas import HealthResponse, StatusResponse
from api.dependencies import get_graph_optional, get_uptime, get_init_error
from api.database import SessionLocal

router = APIRouter(prefix="/api", tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Liveness probe — always responds, even if graph is unavailable."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/health/ready")
async def readiness_check():
    """Readiness probe — checks DB connectivity and graph availability.

    Returns 200 if all dependencies are healthy, 503 otherwise.
    Used by Kubernetes/load balancer to determine if the pod can serve traffic.
    """
    checks = {
        "database": False,
        "graph": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Check DB connectivity
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    # Check graph availability
    graph = get_graph_optional()
    checks["graph"] = graph is not None

    all_healthy = all([checks["database"], checks["graph"]])
    checks["status"] = "ready" if all_healthy else "degraded"

    from fastapi.responses import JSONResponse
    status_code = 200 if all_healthy else 503
    return JSONResponse(content=checks, status_code=status_code)


@router.get("/status", response_model=StatusResponse)
async def system_status():
    """Engine status, session ID, and uptime."""
    graph = get_graph_optional()
    if graph:
        return StatusResponse(
            session_id=graph.session_id,
            execution_mode=graph.execution_mode,
            engine_status=graph.get_engine_status(),
            uptime_seconds=round(get_uptime(), 1),
        )
    return StatusResponse(
        session_id="N/A",
        execution_mode="unavailable",
        engine_status={"error": get_init_error() or "Graph not initialised"},
        uptime_seconds=round(get_uptime(), 1),
    )
