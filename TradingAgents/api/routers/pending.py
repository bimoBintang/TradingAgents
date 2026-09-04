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
# NOTE: get_graph (the shared singleton) is deliberately NOT used here.
# Pending orders, broker credentials, portfolio and persisted kill-switch
# state are all per-user; the approve path builds a per-user graph instead.
from api.auth import get_current_user
from api.models import User, PendingOrder
from api.database import get_db

logger = logging.getLogger("api.pending")

router = APIRouter(prefix="/api/pending-orders", tags=["Pending Orders"])


@router.get("", response_model=List[PendingOrderResponse])
async def list_pending_orders(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List this user's orders awaiting approval.

    Reads only the database. There used to be a second source — the shared
    singleton engine's in-memory queue — but analyses run on a per-user
    graph that is discarded immediately, so that queue was always empty
    AND unscoped: had anything ever landed in it, every user would have
    seen every other user's orders.

    Orders past their expiry are marked EXPIRED here rather than being
    offered for approval, so a stale thesis cannot be traded by someone
    who simply left the tab open.
    """
    now = datetime.now(timezone.utc)

    rows = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.user_id == user.id,
            PendingOrder.status == "PENDING",
        )
        .order_by(PendingOrder.created_at.desc())
        .all()
    )

    orders: List[PendingOrderResponse] = []
    newly_expired = 0

    for row in rows:
        expires_at = row.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now > expires_at:
                row.status = "EXPIRED"
                row.resolved_at = now
                newly_expired += 1
                continue

        key_factors = []
        if row.key_factors:
            try:
                key_factors = json.loads(row.key_factors)
            except json.JSONDecodeError:
                key_factors = []

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
            expires_at=expires_at.isoformat() if expires_at else None,
        ))

    if newly_expired:
        db.commit()
        logger.info("Expired %d stale pending order(s) for user %d", newly_expired, user.id)

    return orders


@router.post("/{idempotency_key}/approve", response_model=ApproveRejectResponse)
async def approve_order(
    idempotency_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Approve a pending order — re-validates every gate, then executes.

    Deliberately does NOT use the shared singleton graph. Pending orders
    belong to a user, and so do the broker credentials, the portfolio and
    the persisted kill-switch state that must be re-checked before this
    trade goes out. A per-user graph is built here for exactly that reason
    (the previous implementation read the singleton's in-memory queue,
    which never contained the order in the first place).

    Approval means "I want this trade", not "skip the checks": the engine
    re-runs the kill switch, RiskController, a fresh price, the order-flow
    guard, leverage setup and protective-stop placement before anything
    reaches the broker.
    """
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user.id,
        )
        .first()
    )

    if db_order is None:
        raise HTTPException(status_code=404, detail="Pending order not found.")

    if db_order.status != "PENDING":
        # Already approved/rejected/expired — never execute twice.
        return ApproveRejectResponse(
            success=False,
            idempotency_key=idempotency_key,
            status=db_order.status,
            message=f"Order is already {db_order.status}; it cannot be approved again.",
        )

    expires_at = db_order.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            db_order.status = "EXPIRED"
            db_order.resolved_at = datetime.now(timezone.utc)
            db.commit()
            return ApproveRejectResponse(
                success=False,
                idempotency_key=idempotency_key,
                status="EXPIRED",
                message=(
                    "This order has expired and was not executed. The market has moved "
                    "since the analysis; run a new analysis instead of trading a stale thesis."
                ),
            )

    if not db_order.decision_json:
        raise HTTPException(
            status_code=422,
            detail="Pending order has no stored decision payload; it cannot be executed safely.",
        )

    # Build a graph bound to THIS user's config (their broker, their
    # portfolio, their persisted risk state).
    try:
        from api.dependencies import init_graph
        from api.user_context import get_user_config

        user_graph = init_graph(config=get_user_config(db, user.id))
    except Exception as e:
        logger.error("Could not build execution context for user %d: %s", user.id, e)
        raise HTTPException(status_code=503, detail=f"Execution engine unavailable: {e}")

    if not user_graph or not user_graph.execution_engine:
        raise HTTPException(status_code=503, detail="Execution engine not available")

    result = user_graph.execution_engine.execute_approved_order(
        decision_json=db_order.decision_json,
        idempotency_key=idempotency_key,
    )

    resolved_at = datetime.now(timezone.utc)

    if result is None:
        # A gate rejected it (kill switch, risk limits, order flow, sizing).
        # The order stays PENDING so it is not silently lost — previously
        # the row was marked APPROVED regardless of what actually happened,
        # leaving the database claiming a trade that never executed.
        logger.warning(
            "Approved order %s for user %d was blocked by a safety gate.",
            idempotency_key, user.id,
        )
        return ApproveRejectResponse(
            success=False,
            idempotency_key=idempotency_key,
            status="BLOCKED",
            message=(
                "Approval accepted, but a safety check blocked execution "
                "(kill switch, risk limits, order flow, or sizing). Nothing was sent to the broker."
            ),
        )

    db_order.status = "APPROVED"
    db_order.resolved_at = resolved_at
    db_order.order_result_json = json.dumps({
        "order_id": result.order_id,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "filled_quantity": result.filled_quantity,
        "filled_price": result.filled_price,
    }, default=str)
    db.commit()

    try:
        from api.services.balance_sync import sync_user_balance
        sync_user_balance(user.id, db=db)
    except Exception as e:
        logger.error("Post-approval balance sync failed for user %d: %s", user.id, e)

    return ApproveRejectResponse(
        success=True,
        idempotency_key=idempotency_key,
        status="APPROVED",
        message=f"Order executed: {result.status.value if hasattr(result.status, 'value') else str(result.status)}",
        order_id=result.order_id,
    )


@router.post("/{idempotency_key}/reject", response_model=ApproveRejectResponse)
async def reject_order(
    idempotency_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending order — marks it resolved without executing.

    Resolved purely against the database, scoped to this user. It used to
    also require the order to be present in the shared singleton engine's
    in-memory queue, which meant a user could not reject their own order
    because it was never there.
    """
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user.id,
        )
        .first()
    )

    if db_order is None:
        raise HTTPException(status_code=404, detail="Pending order not found.")

    if db_order.status != "PENDING":
        return ApproveRejectResponse(
            success=False,
            idempotency_key=idempotency_key,
            status=db_order.status,
            message=f"Order is already {db_order.status}.",
        )

    db_order.status = "REJECTED"
    db_order.resolved_at = datetime.now(timezone.utc)
    db.commit()

    return ApproveRejectResponse(
        success=True,
        idempotency_key=idempotency_key,
        status="REJECTED",
        message="Order rejected — nothing was sent to the broker.",
    )
