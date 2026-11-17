"""Approve / reject pending orders.

Shared by the REST router, the MCP server and the dashboard so that every path goes through
the same atomic claim, per-owner graph and engine re-validation. No HTTP types in here:
errors are raised as PendingOrderError and mapped by the caller.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from api.models import PendingOrder
from api.schemas import ApproveRejectResponse

logger = logging.getLogger("api.pending_orders")


class PendingOrderError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def approve(db: Session, user_id: int, idempotency_key: str) -> ApproveRejectResponse:
    """Approve a pending order: re-validates every gate, then executes.

    Approval means "I want this trade", not "skip the checks": the engine re-runs the kill
    switch, RiskController, a fresh price, the order-flow guard, leverage setup and
    protective-stop placement before anything reaches the broker.
    """
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user_id,
        )
        .first()
    )

    if db_order is None:
        raise PendingOrderError(404, "Pending order not found.")

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
        raise PendingOrderError(
            422, "Pending order has no stored decision payload; it cannot be executed safely."
        )

    # Atomic claim: the PENDING check above is check-then-act, so two concurrent
    # approvals could both pass it and both trade. Only one UPDATE can flip
    # PENDING -> EXECUTING; the loser gets rowcount 0 and stops here.
    claimed = (
        db.query(PendingOrder)
        .filter(PendingOrder.id == db_order.id, PendingOrder.status == "PENDING")
        .update({"status": "EXECUTING"}, synchronize_session=False)
    )
    db.commit()
    if claimed == 0:
        return ApproveRejectResponse(
            success=False,
            idempotency_key=idempotency_key,
            status="EXECUTING",
            message="Order is already being processed; it cannot be approved again.",
        )
    db.refresh(db_order)

    def _release() -> None:
        # Give the order back so it is not stranded in EXECUTING when nothing was sent.
        db.query(PendingOrder).filter(
            PendingOrder.id == db_order.id, PendingOrder.status == "EXECUTING"
        ).update({"status": "PENDING"}, synchronize_session=False)
        db.commit()

    # Build a graph bound to THIS user's config (their broker, their
    # portfolio, their persisted risk state).
    try:
        from api.dependencies import init_graph
        from api.user_context import get_user_config

        user_graph = init_graph(config=get_user_config(db, user_id))
    except Exception as e:
        _release()
        logger.error("Could not build execution context for user %d: %s", user_id, e)
        raise PendingOrderError(503, f"Execution engine unavailable: {e}")

    if not user_graph or not user_graph.execution_engine:
        _release()
        raise PendingOrderError(503, "Execution engine not available")

    # shortcut: if the process dies mid-call the order stays EXECUTING (never
    # re-sent, needs a manual look); a janitor sweep is the upgrade.
    try:
        result = user_graph.execution_engine.execute_approved_order(
            decision_json=db_order.decision_json,
            idempotency_key=idempotency_key,
        )
    except Exception:
        # Unknown whether anything reached the broker: do NOT release, a retry could double-trade.
        logger.exception("Approved order %s raised during execution; left EXECUTING for review.", idempotency_key)
        raise

    resolved_at = datetime.now(timezone.utc)

    if result is None:
        _release()
        # A gate rejected it (kill switch, risk limits, order flow, sizing).
        # The order stays PENDING so it is not silently lost — previously
        # the row was marked APPROVED regardless of what actually happened,
        # leaving the database claiming a trade that never executed.
        logger.warning(
            "Approved order %s for user %d was blocked by a safety gate.",
            idempotency_key, user_id,
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
        sync_user_balance(user_id, db=db)
    except Exception as e:
        logger.error("Post-approval balance sync failed for user %d: %s", user_id, e)

    return ApproveRejectResponse(
        success=True,
        idempotency_key=idempotency_key,
        status="APPROVED",
        message=f"Order executed: {result.status.value if hasattr(result.status, 'value') else str(result.status)}",
        order_id=result.order_id,
    )


def reject(db: Session, user_id: int, idempotency_key: str) -> ApproveRejectResponse:
    """Mark a pending order rejected without executing (database only, scoped to the owner)."""
    db_order = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.idempotency_key == idempotency_key,
            PendingOrder.user_id == user_id,
        )
        .first()
    )

    if db_order is None:
        raise PendingOrderError(404, "Pending order not found.")

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
