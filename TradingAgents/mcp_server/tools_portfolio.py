"""Portfolio & analysis MCP tools — Fase 2.

Reuses the same DB models, TradingAgentsGraph singleton, and analysis
task pipeline as the REST API (api/routers/portfolio.py,
api/routers/analysis.py) so results are consistent with what the
dashboard shows — no separate logic path to drift out of sync.

All tools here are READ-ONLY / analysis-only. Nothing in this file
places, approves, or modifies a trade — that's deliberately deferred
to a later phase that routes through the existing pending-order
approval flow (api/routers/pending.py), never bypassing it.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from uuid import uuid4

from api.models import Position, Trade, TaskResult
from api.user_context import ensure_portfolio
from mcp_server.context import db_session, resolve_mcp_user

logger = logging.getLogger("mcp_server.tools_portfolio")

# Max time to wait for an analysis run to finish before returning a
# "still running" message instead of blocking the MCP client forever.
_ANALYSIS_TIMEOUT_SECONDS = 180
_ANALYSIS_POLL_INTERVAL_SECONDS = 2


def read_portfolio() -> str:
    """Get the current portfolio: cash balance, total equity, PnL, win rate,
    max drawdown, and all open positions.

    Returns:
        str: A formatted summary of the portfolio state.
    """
    with db_session() as db:
        user = resolve_mcp_user(db)
        ps = ensure_portfolio(db, user)
        positions = db.query(Position).filter(Position.portfolio_id == ps.id).all()

        daily_pnl = "N/A" if ps.daily_pnl is None else f"${ps.daily_pnl:,.2f}"
        lines = [
            f"Portfolio for {user.email}",
            f"Cash balance:  ${ps.cash_balance:,.2f}",
            f"Total equity:  ${ps.total_equity:,.2f}",
            f"Total P&L:     ${ps.total_pnl:,.2f}",
            f"Daily P&L:     {daily_pnl}",
            f"Win rate:      {ps.win_rate * 100:.1f}%",
            f"Max drawdown:  {ps.max_drawdown_pct * 100:.1f}%",
            f"Total trades:  {ps.total_trades}",
            "",
            f"Open positions ({len(positions)}):",
        ]
        if not positions:
            lines.append("  (none)")
        else:
            for p in positions:
                lines.append(
                    f"  {p.ticker:<10} {p.side:<5} qty={p.quantity:g} "
                    f"entry=${p.entry_price:.2f} current=${p.current_price:.2f} "
                    f"uPnL=${p.unrealized_pnl or 0:.2f}"
                )
        return "\n".join(lines)


def list_recent_trades(limit: int = 20) -> str:
    """List the most recent filled trades for the portfolio, newest first.

    Args:
        limit: Maximum number of trades to return (default 20, max 100).

    Returns:
        str: A formatted list of recent trades.
    """
    limit = max(1, min(limit, 100))
    with db_session() as db:
        user = resolve_mcp_user(db)
        ps = ensure_portfolio(db, user)
        trades = (
            db.query(Trade)
            .filter(Trade.portfolio_id == ps.id)
            .order_by(Trade.fill_time.desc())
            .limit(limit)
            .all()
        )
        if not trades:
            return "No trades yet."
        lines = [f"Last {len(trades)} trade(s) for {user.email}:"]
        for t in trades:
            pnl = "N/A" if t.realized_pnl is None else f"${t.realized_pnl:.2f}"
            lines.append(
                f"  {t.fill_time:%Y-%m-%d %H:%M} {t.ticker:<10} {t.action:<5} "
                f"qty={t.filled_qty:g} price=${t.fill_price:.2f} "
                f"pnl={pnl} status={t.status}"
            )
        return "\n".join(lines)


def run_analysis(ticker: str, trade_date: str | None = None) -> str:
    """Run the full TradingAgents multi-agent analysis pipeline for a ticker
    and wait for it to finish (technical, fundamental, news, and
    sentiment analysts + risk management debate).

    This can take 1-3 minutes since it involves several LLM calls. If it
    doesn't finish within the timeout, a status message is returned instead
    and the analysis keeps running in the background (check the dashboard's
    Analysis tab, or call this tool again later — it will start a new run).

    Args:
        ticker: Ticker symbol to analyze, e.g. AAPL, BTC-USD.
        trade_date: Date to analyze as of, in yyyy-mm-dd format. Defaults to today.

    Returns:
        str: The trading decision and a summary of analyst reports, or a
             status/error message if analysis failed or timed out.
    """
    from api.dependencies import get_graph_optional, init_graph
    from api.tasks import run_analysis_thread

    graph = get_graph_optional() or init_graph()
    if graph is None:
        return (
            "TradingAgentsGraph is not available — the server is running in "
            "degraded mode (check LLM API keys in .env). Cannot run analysis."
        )

    ticker = ticker.upper().strip()
    trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")

    with db_session() as db:
        user = resolve_mcp_user(db)
        task_id = str(uuid4())

        task_row = TaskResult(task_id=task_id, user_id=user.id, ticker=ticker, status="queued")
        db.add(task_row)
        db.commit()

        # auto_execute=False — analysis-only. Trade execution is a
        # separate, explicitly-guarded phase (see module docstring).
        run_analysis_thread(task_id, user.id, ticker, trade_date, auto_execute=False)

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
                f"Task ID: {task_id}. It continues in the background — check "
                "the dashboard's Analysis tab for the result."
            )

        result = json.loads(task_row.result_json) if task_row.result_json else {}
        decision = result.get("decision") or {}
        reports = result.get("reports") or {}

        lines = [
            f"Analysis for {ticker} ({trade_date}):",
            f"Decision:   {decision.get('action', 'N/A')}",
            f"Confidence: {decision.get('confidence', 'N/A')}",
            f"Reasoning:  {decision.get('reasoning', 'N/A')}",
        ]
        if reports:
            lines.append("")
            lines.append("Analyst reports:")
            for name, text in reports.items():
                summary = (text or "").strip().replace("\n", " ")
                if len(summary) > 300:
                    summary = summary[:300] + "..."
                lines.append(f"  [{name}] {summary}")
        return "\n".join(lines)
