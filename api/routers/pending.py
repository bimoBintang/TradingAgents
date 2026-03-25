"""Pending trade order endpoints — approval flow for live trading.

When require_confirmation=True, the ExecutionEngine saves orders to a
pending queue instead of executing them immediately. These endpoints
allow the frontend to list, approve, and reject pending orders.
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from api.schemas import PendingOrderResponse, ApproveRejectResponse
from api.dependencies import get_graph
from api.auth import get_current_user
from api.models import User, PendingOrder
from api.database import get_db

logger = logging.getLogger("api.pending")

router = APIRouter(prefix="/api/pending-orders", tags=["Pending Orders"])


@router.get("", response_model=List[PendingOrderResponse])
async def list_pending_orders(
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all pending orders awaiting approval.

    Returns orders from both the in-memory execution engine queue
    and the database (for persistence across restarts).
    """
    orders = []

    # Source 1: In-memory pending orders from execution engine
    if graph and graph.execution_engine:
        for pending in graph.execution_engine.get_pending_orders():
            orders.append(PendingOrderResponse(
                id=pending.get("idempotency_key", ""),
                idempotency_key=pending.get("idempotency_key", ""),
                ticker=pending.get("ticker", ""),
                action=pending.get("action", ""),
                quantity=pending.get("quantity", 0),
                price=pending.get("price", 0),
                value=pending.get("value", 0),
                confidence=pending.get("confidence", 0),
                stop_loss_pct=pending.get("stop_loss_pct"),
                take_profit_pct=pending.get("take_profit_pct"),
                order_type=str(pending.get("order_type", "MARKET")),
                time_horizon=pending.get("time_horizon"),
                reasoning=pending.get("reasoning", ""),
                key_factors=pending.get("key_factors", []),
                risk_score=None,
                status="PENDING",
                created_at=datetime.now(timezone.utc).isoformat(),
            ))

    # Source 2: Database pending orders (for persistence)
    db_pending = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.user_id == user.id,
            PendingOrder.status == "PENDING",
        )
        .order_by(PendingOrder.created_at.desc())
        .all()
    )

    seen_keys = {o.idempotency_key for o in orders}
    for row in db_pending:
        if row.idempotency_key not in seen_keys:
            key_factors = []
            if row.key_factors:
                try:
                    key_factors = json.loads(row.key_factors)
                except json.JSONDecodeError:
                    pass

            orders.append(PendingOrderResponse(
                id=str(row.id),
                idempotency_key=row.idempotency_key,
                ticker=row.ticker,
                action=row.action,
                quantity=row.quantity,
                price=row.price,
                value=row.value,
                confidence=row.confidence,
                stop_loss_pct=row.stop_loss_pct,
                take_profit_pct=row.take_profit_pct,
                order_type=row.order_type or "MARKET",
                time_horizon=row.time_horizon,
                reasoning=row.reasoning or "",
                key_factors=key_factors,
                risk_score=row.risk_score,
                status=row.status,
                created_at=row.created_at.isoformat() if row.created_at else "",
                expires_at=row.expires_at.isoformat() if row.expires_at else None,
            ))

    return orders


@router.post("/{idempotency_key}/approve", response_model=ApproveRejectResponse)
async def approve_order(
    idempotency_key: str,
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a pending order — sends it to the broker for execution."""
    if not graph or not graph.execution_engine:
        raise HTTPException(status_code=503, detail="Execution engine not available")

    result = graph.execution_engine.approve_pending_order(idempotency_key)

    # Also update DB record if exists
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user.id,
        )
        .first()
    )
    if db_order:
        db_order.status = "APPROVED"
        db_order.resolved_at = datetime.now(timezone.utc)
        if result:
            db_order.order_result_json = json.dumps({
                "order_id": result.order_id,
                "status": result.status.value if hasattr(result.status, "value") else str(result.status),
                "filled_quantity": result.filled_quantity,
                "filled_price": result.filled_price,
            }, default=str)
        db.commit()

    if result:
        return ApproveRejectResponse(
            success=True,
            idempotency_key=idempotency_key,
            status="APPROVED",
            message=f"Order executed: {result.status.value if hasattr(result.status, 'value') else str(result.status)}",
            order_id=result.order_id,
        )
    else:
        return ApproveRejectResponse(
            success=False,
            idempotency_key=idempotency_key,
            status="FAILED",
            message="Order not found in pending queue or execution failed.",
        )


@router.post("/{idempotency_key}/reject", response_model=ApproveRejectResponse)
async def reject_order(
    idempotency_key: str,
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending order — removes it without executing."""
    if not graph or not graph.execution_engine:
        raise HTTPException(status_code=503, detail="Execution engine not available")

    success = graph.execution_engine.reject_pending_order(idempotency_key)

    # Also update DB record if exists
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user.id,
        )
        .first()
    )
    if db_order:
        db_order.status = "REJECTED"
        db_order.resolved_at = datetime.now(timezone.utc)
        db.commit()

    return ApproveRejectResponse(
        success=success,
        idempotency_key=idempotency_key,
        status="REJECTED" if success else "NOT_FOUND",
        message="Order rejected" if success else "Order not found in pending queue",
    )
