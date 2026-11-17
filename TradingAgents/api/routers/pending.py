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
from api.services import pending_orders

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
    """Approve a pending order (logic in api/services/pending_orders.py)."""
    try:
        return pending_orders.approve(db, user.id, idempotency_key)
    except pending_orders.PendingOrderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/{idempotency_key}/reject", response_model=ApproveRejectResponse)
async def reject_order(
    idempotency_key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reject a pending order without executing it."""
    try:
        return pending_orders.reject(db, user.id, idempotency_key)
    except pending_orders.PendingOrderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
