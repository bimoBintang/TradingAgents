"""Trading MCP tools — Fase 3: propose, list, approve, reject orders.

SAFETY CONTRACT (do not weaken this without a very deliberate reason):

  - `propose_trade()` runs the analysis pipeline and, if the agents
    decide to trade, ALWAYS lands in the pending-order queue for
    human approval — it never places a live order itself, regardless
    of how `execution.require_confirmation` is configured in the
    dashboard. See the force-confirmation comment below.

  - `approve_pending_order()` is the ONLY tool in this file that can
    cause a real broker order. It requires an explicit
    `idempotency_key` the caller must already have (from
    `propose_trade`/`list_pending_orders`'s output) — an LLM should
    only call it after a human has explicitly said to approve that
    specific order, never speculatively.

  - Every write here goes through the exact same ExecutionEngine /
    PendingOrder DB code path as api/routers/pending.py, so the
    dashboard's Pending Orders panel and this MCP server always agree
    on what's queued.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from api.models import PendingOrder, TaskResult
from mcp_server.context import db_session, resolve_mcp_user

logger = logging.getLogger("mcp_server.tools_trading")

_ANALYSIS_TIMEOUT_SECONDS = 180
_ANALYSIS_POLL_INTERVAL_SECONDS = 2


def _get_graph():
    from api.dependencies import get_graph_optional, init_graph

    return get_graph_optional() or init_graph()


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
    """List trade orders awaiting human approval in the dashboard.

    Combines the execution engine's in-memory queue (orders proposed in
    this MCP server session) with any orders persisted to the database
    (e.g. proposed earlier via the dashboard). Each order has an
    idempotency_key needed by approve_pending_order/reject_pending_order.

    Returns:
        str: A formatted list of pending orders, or a message if none.
    """
    graph = _get_graph()
    engine_orders = graph.execution_engine.get_pending_orders() if graph and graph.execution_engine else []

    with db_session() as db:
        user = resolve_mcp_user(db)
        db_orders = (
            db.query(PendingOrder)
            .filter(PendingOrder.user_id == user.id, PendingOrder.status == "PENDING")
            .order_by(PendingOrder.created_at.desc())
            .all()
        )

    seen = {o.get("idempotency_key") for o in engine_orders}
    rows = [_format_pending(o) for o in engine_orders]
    rows += [_format_pending(o) for o in db_orders if o.idempotency_key not in seen]

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

    graph = _get_graph()
    if graph is None:
        return (
            "TradingAgentsGraph is not available — the server is running in "
            "degraded mode (check LLM API keys in .env). Cannot propose a trade."
        )
    if graph.execution_engine is None:
        return "Execution engine is not configured (check execution settings). Cannot propose a trade."

    # Force manual confirmation for THIS MCP server's graph instance,
    # regardless of the dashboard's `execution.require_confirmation`
    # setting. The MCP server runs its own process-local graph (see
    # api/dependencies.py's init_graph()) separate from the dashboard
    # backend's, so this only affects trades proposed through this MCP
    # server — it never weakens the dashboard's own configuration.
    graph.execution_engine.require_confirmation = True

    ticker = ticker.upper().strip()
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")

    with db_session() as db:
        user = resolve_mcp_user(db)
        task_id = str(uuid4())

        task_row = TaskResult(task_id=task_id, user_id=user.id, ticker=ticker, status="queued")
        db.add(task_row)
        db.commit()

        # auto_execute=True lets the pipeline propose a trade — but
        # thanks to require_confirmation=True above, "propose" is as
        # far as it can go without a separate approve_pending_order() call.
        run_analysis_thread(task_id, user.id, ticker, trade_date, auto_execute=True)

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
    """Approve a specific pending order — sends it to the broker for execution.

    ⚠️ This places a REAL order (or a paper-trading order, depending on
    the dashboard's execution mode). Only call this after a human has
    explicitly confirmed they want THIS specific order approved — never
    speculatively or as part of an automated chain.

    Args:
        idempotency_key: The exact key from list_pending_orders/propose_trade's output.

    Returns:
        str: The execution result, or an error if the order wasn't found.
    """
    graph = _get_graph()
    if not graph or not graph.execution_engine:
        return "Execution engine not available."

    result = graph.execution_engine.approve_pending_order(idempotency_key)

    with db_session() as db:
        user = resolve_mcp_user(db)
        db_order = (
            db.query(PendingOrder)
            .filter(PendingOrder.idempotency_key == idempotency_key, PendingOrder.user_id == user.id)
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

    if not result:
        return f"Order {idempotency_key} not found in the pending queue (already resolved, or expired)."

    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    return (
        f"Order {idempotency_key} approved and submitted.\n"
        f"Status: {status}\n"
        f"Filled: {result.filled_quantity} @ ${result.filled_price}\n"
        f"Order ID: {result.order_id}"
    )


def reject_pending_order(idempotency_key: str) -> str:
    """Reject a pending order — removes it from the queue without executing it.

    Args:
        idempotency_key: The exact key from list_pending_orders/propose_trade's output.

    Returns:
        str: Confirmation, or an error if the order wasn't found.
    """
    graph = _get_graph()
    if not graph or not graph.execution_engine:
        return "Execution engine not available."

    success = graph.execution_engine.reject_pending_order(idempotency_key)

    with db_session() as db:
        user = resolve_mcp_user(db)
        db_order = (
            db.query(PendingOrder)
            .filter(PendingOrder.idempotency_key == idempotency_key, PendingOrder.user_id == user.id)
            .first()
        )
        if db_order:
            db_order.status = "REJECTED"
            db_order.resolved_at = datetime.now(timezone.utc)
            db.commit()

    if success or db_order:
        return f"Order {idempotency_key} rejected."
    return f"Order {idempotency_key} not found in the pending queue."
