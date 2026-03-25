"""Analysis endpoint — runs agent analysis as a background task.

Uses Celery if available (production), falls back to threading (local dev).
Results persisted to TaskResult DB table for both modes.
"""

import json
import logging
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas import AnalyzeRequest, AnalyzeResponse, AnalysisResultResponse
from api.dependencies import get_graph
from api.auth import get_current_user
from api.models import User, TaskResult
from api.database import get_db

logger = logging.getLogger("api.analysis")

router = APIRouter(prefix="/api", tags=["Analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    body: AnalyzeRequest,
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a ticker analysis for the authenticated user.

    Dispatches to Celery worker if available, otherwise uses a background thread.
    Returns a task_id immediately. Poll GET /api/analyze/{task_id} for results.
    """
    task_id = str(uuid4())
    trade_date = body.trade_date or datetime.now().strftime("%Y-%m-%d")
    ticker = body.ticker.upper()

    # Create persistent task record
    task_row = TaskResult(
        task_id=task_id,
        user_id=user.id,
        ticker=ticker,
        status="queued",
    )
    db.add(task_row)
    db.commit()

    # Dispatch — Celery or thread fallback
    try:
        from api.celery_app import is_celery_available
        if is_celery_available():
            from api.tasks import run_analysis_task
            run_analysis_task.delay(task_id, user.id, ticker, trade_date, body.auto_execute)
            logger.info("Analysis %s dispatched to Celery (user=%d)", task_id, user.id)
        else:
            raise ImportError("Celery not available")
    except (ImportError, Exception):
        # Thread fallback
        from api.tasks import run_analysis_thread
        run_analysis_thread(task_id, user.id, ticker, trade_date, body.auto_execute)
        logger.info("Analysis %s started via thread fallback (user=%d)", task_id, user.id)

    return AnalyzeResponse(
        task_id=task_id,
        status="queued",
        message=f"Analysis for {ticker} ({trade_date}) started.",
    )


@router.get("/analyze/{task_id}", response_model=AnalysisResultResponse)
async def get_analysis_result(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll for analysis result — reads from DB, scoped to authenticated user."""
    task_row = (
        db.query(TaskResult)
        .filter(TaskResult.task_id == task_id, TaskResult.user_id == user.id)
        .first()
    )
    if not task_row:
        return AnalysisResultResponse(
            task_id=task_id,
            status="not_found",
            error="No analysis with this task_id.",
        )

    # Parse result JSON if completed
    decision = None
    order_result = None
    reports = None
    if task_row.result_json:
        try:
            result = json.loads(task_row.result_json)
            decision = result.get("decision")
            order_result = result.get("order_result")
            reports = result.get("reports")
        except json.JSONDecodeError:
            pass

    return AnalysisResultResponse(
        task_id=task_row.task_id,
        status=task_row.status,
        decision=decision,
        order_result=order_result,
        reports=reports,
        error=task_row.error,
    )
