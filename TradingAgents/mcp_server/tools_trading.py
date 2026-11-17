"""Trading MCP tools: propose, list, approve, reject orders.

SAFETY CONTRACT (do not weaken this without a very deliberate reason):

  - `propose_trade()` runs the analysis pipeline and, if the agents decide to trade, ALWAYS
    lands in the pending-order queue for human approval. It passes force_confirmation=True to
    the analysis task, which sets require_confirmation on the graph that actually runs, so it
    never places a live order regardless of `execution.require_confirmation` in the config.

  - `approve_pending_order()` is the ONLY tool here that can cause a real broker order. It
    requires an explicit `idempotency_key` the caller must already have. An LLM should only call
    it after a human has explicitly said to approve that specific order.

  - Approve/reject use api/services/pending_orders.py: the same atomic claim, per-owner graph
    and engine re-validation as the dashboard, so both always agree on what is queued.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from uuid import uuid4

from api.models import PendingOrder, TaskResult
from mcp_server.context import db_session, resolve_mcp_user

logger = logging.getLogger("mcp_server.tools_trading")

_ANALYSIS_TIMEOUT_SECONDS = 180
_ANALYSIS_POLL_INTERVAL_SECONDS = 2


def _format_pending(p: dict | PendingOrder) -> str:
    """Render one pending order, from either the in-memory engine dict
    shape or a PendingOrder DB row, in a single consistent format."""
    if isinstance(p, PendingOrder):
        key, ticker, action, qty, price, value, confidence, reasoning = (
            p.idempotency_key, p.ticker, p.action, p.quantity, p.price,
            p.value, p.confidence, p.reasoning or "",
        )
    else:
        key, ticker, action, qty, price, value, confidence, reasoning = (
            p.get("idempotency_key", ""), p.get("ticker", ""), p.get("action", ""),
            p.get("quantity", 0), p.get("price", 0), p.get("value", 0),
            p.get("confidence", 0), p.get("reasoning", ""),
        )
    return (
        f"  [{key}] {action} {qty:g} {ticker} @ ${price:.2f} "
        f"(value=${value:,.2f}, confidence={confidence:.0%})\n"
        f"    Reasoning: {reasoning}"
    )


def list_pending_orders() -> str:
    """List trade orders awaiting approval (the same queue the dashboard shows).

    Each order has an idempotency_key needed by approve_pending_order/reject_pending_order.

    Returns:
        str: A formatted list of pending orders, or a message if none.
    """
    with db_session() as db:
        user = resolve_mcp_user(db)
        db_orders = (
            db.query(PendingOrder)
            .filter(PendingOrder.user_id == user.id, PendingOrder.status == "PENDING")
            .order_by(PendingOrder.created_at.desc())
            .all()
        )
        rows = [_format_pending(o) for o in db_orders]

    if not rows:
        return "No pending orders awaiting approval."
    return f"{len(rows)} pending order(s):\n" + "\n".join(rows)


def propose_trade(ticker: str, trade_date: str | None = None) -> str:
    """Run the multi-agent analysis for a ticker and, if it decides to
    trade, submit the order for human approval.

    This NEVER places a live order by itself — no matter what the
    dashboard's execution settings say, the resulting order always
    lands in the pending-order queue. A human must explicitly call
    approve_pending_order() (typically from the dashboard, or by
    asking you to do it) before anything is sent to a broker.

    Args:
        ticker: Ticker symbol to analyze and potentially trade, e.g. AAPL, BTC-USD.
        trade_date: Date to analyze as of, yyyy-mm-dd. Defaults to today.

    Returns:
        str: The decision, and — if a trade was proposed — its pending
             order details including the idempotency_key to approve/reject it.
    """
    from api.tasks import run_analysis_thread

    ticker = ticker.upper().strip()
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")

    with db_session() as db:
        user = resolve_mcp_user(db)
        task_id = str(uuid4())

        task_row = TaskResult(task_id=task_id, user_id=user.id, ticker=ticker, status="queued")
        db.add(task_row)
        db.commit()

        # auto_execute=True lets the pipeline propose a trade; force_confirmation=True makes
        # "propose" as far as it can go without a separate approve_pending_order() call.
        run_analysis_thread(task_id, user.id, ticker, trade_date, auto_execute=True, force_confirmation=True)

        deadline = time.monotonic() + _ANALYSIS_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(_ANALYSIS_POLL_INTERVAL_SECONDS)
            db.refresh(task_row)
            if task_row.status in ("completed", "failed"):
                break

        if task_row.status == "failed":
            return f"Analysis for {ticker} failed: {task_row.error or 'unknown error'}"
        if task_row.status != "completed":
            return (
                f"Analysis for {ticker} is still running after "
                f"{_ANALYSIS_TIMEOUT_SECONDS}s (status={task_row.status}). "
                f"Task ID: {task_id}. Check the dashboard's Analysis tab."
            )

        result = json.loads(task_row.result_json) if task_row.result_json else {}
        decision = result.get("decision") or {}

        # Find the pending order this task just created, if the
        # decision was to trade.
        pending = (
            db.query(PendingOrder)
            .filter(PendingOrder.task_id == task_id, PendingOrder.user_id == user.id)
            .order_by(PendingOrder.created_at.desc())
            .first()
        )

        lines = [
            f"Analysis for {ticker} ({trade_date}):",
            f"Decision: {decision.get('action', 'N/A')} "
            f"(confidence: {decision.get('confidence', 'N/A')})",
            f"Reasoning: {decision.get('reasoning', 'N/A')}",
        ]
        if pending:
            lines.append("")
            lines.append("A trade was proposed and is now awaiting your approval:")
            lines.append(_format_pending(pending))
            lines.append(
                "Nothing has been sent to the broker. Approve it from the "
                "dashboard's Pending Orders panel, or ask me to call "
                "approve_pending_order with the key above if you want me to."
            )
        return "\n".join(lines)


def approve_pending_order(idempotency_key: str) -> str:
    """Approve a specific pending order: sends it to the broker for execution.

    ⚠️ This places a REAL order (or a paper-trading order, depending on the execution mode).
    Only call this after a human has explicitly confirmed they want THIS specific order approved,
    never speculatively or as part of an automated chain. Every safety check (kill switch, risk
    limits, fresh price, order flow, stop placement) is re-run before anything is sent.

    Args:
        idempotency_key: The exact key from list_pending_orders/propose_trade's output.

    Returns:
        str: The execution result, or why it was not executed.
    """
    from api.services import pending_orders

    with db_session() as db:
        user = resolve_mcp_user(db)
        try:
            res = pending_orders.approve(db, user.id, idempotency_key)
        except pending_orders.PendingOrderError as e:
            return f"Order {idempotency_key}: {e.detail}"
    if res.success:
        return f"Order {idempotency_key} approved and submitted.\n{res.message}\nOrder ID: {res.order_id}"
    return f"Order {idempotency_key} was NOT executed ({res.status}): {res.message}"


def reject_pending_order(idempotency_key: str) -> str:
    """Reject a pending order: marks it resolved without executing it.

    Args:
        idempotency_key: The exact key from list_pending_orders/propose_trade's output.

    Returns:
        str: Confirmation, or why it could not be rejected.
    """
    from api.services import pending_orders

    with db_session() as db:
        user = resolve_mcp_user(db)
        try:
            res = pending_orders.reject(db, user.id, idempotency_key)
        except pending_orders.PendingOrderError as e:
            return f"Order {idempotency_key}: {e.detail}"
    return res.message if res.success else f"Order {idempotency_key} not rejected ({res.status}): {res.message}"
