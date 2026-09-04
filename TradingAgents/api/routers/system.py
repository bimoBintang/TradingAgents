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
    from api.crypto import IS_EPHEMERAL_KEY

    checks = {
        "database": False,
        "graph": False,
        # Surfaced here so an operator can SEE the ephemeral-key condition
        # instead of having to notice one startup log line. On an ephemeral
        # key, stored exchange credentials do not survive a restart and
        # live trading silently degrades to paper.
        "persistent_credential_key": not IS_EPHEMERAL_KEY,
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

    # Readiness deliberately does NOT gate on the credential key. In
    # production the process refuses to start without FERNET_KEY (see
    # api/crypto.py), so reaching this line there already proves the key is
    # persistent. Failing readiness for it would only break local dev,
    # where an ephemeral key is fine — so it is reported as a warning
    # instead of pulling the instance out of rotation.
    all_healthy = all([checks["database"], checks["graph"]])
    checks["status"] = "ready" if all_healthy else "degraded"

    if IS_EPHEMERAL_KEY:
        checks["warnings"] = [
            "FERNET_KEY is not set — stored exchange credentials will not survive a "
            "restart and live trading will silently fall back to paper. Do not trade "
            "real money in this state."
        ]

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
