"""Autopilot MCP tools: control and observe the autonomous AI.

Thin wrappers over api/services/autopilot.py, the same service the dashboard uses, so every
client (dashboard, Claude Desktop, a local-model agent, ...) sees and changes the same state.
Goals make the AI stop by itself: profit target, loss limit, end time. Stopping means no new
analyses; open positions keep their broker-side stops.
"""

from __future__ import annotations

import json
from typing import List, Optional

from mcp_server.context import db_session


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


def get_autopilot_status() -> str:
    """Current state of the autonomous AI: running/paused/stopped (and why), the market and mode it
    trades, goals and progress (equity change since start, time left), watchlist with next run
    times, and whether orders need your approval.

    Returns:
        str: JSON status.
    """
    from api.services import autopilot
    with db_session() as db:
        return _dump(autopilot.status(db))


def start_autopilot(target_profit_pct: Optional[float] = None, max_loss_pct: Optional[float] = None,
                    end_at: Optional[str] = None) -> str:
    """Start the autonomous AI with goals; it stops by itself when one is met.

    Set at least one goal so it does not run forever. Only call this when the user explicitly asks
    to start it. Orders still follow the configured approval mode.

    Args:
        target_profit_pct: Stop when equity is up this percent since start (e.g. 10).
        max_loss_pct: Stop when equity is down this percent since start (e.g. 5).
        end_at: ISO timestamp (UTC) at which the run ends, e.g. 2026-12-01T00:00:00Z.

    Returns:
        str: JSON status after starting, or the validation error.
    """
    from api.services import autopilot
    if target_profit_pct is None and max_loss_pct is None and end_at is None:
        return "Refused: set at least one goal (target_profit_pct, max_loss_pct or end_at) so the AI does not run forever."
    with db_session() as db:
        try:
            return _dump(autopilot.start(db, target_profit_pct, max_loss_pct, end_at))
        except ValueError as e:
            return f"Not started: {e}"


def pause_autopilot() -> str:
    """Pause the autonomous AI (no new analyses). Open positions keep their stops. Reversible with resume_autopilot.

    Returns:
        str: JSON status.
    """
    from api.services import autopilot
    with db_session() as db:
        return _dump(autopilot.pause(db))


def resume_autopilot() -> str:
    """Resume a paused run, keeping its goals and baseline. A run that already reached a goal must be started again.

    Returns:
        str: JSON status, or why it cannot resume.
    """
    from api.services import autopilot
    with db_session() as db:
        try:
            return _dump(autopilot.resume(db))
        except ValueError as e:
            return f"Not resumed: {e}"


def set_watchlist(tickers: List[str]) -> str:
    """Replace the list of tickers the autonomous AI analyzes, e.g. ["BTC-USD", "ETH-USD"] or ["EURUSD"].

    Args:
        tickers: Ticker symbols.

    Returns:
        str: JSON status.
    """
    from api.services import autopilot
    with db_session() as db:
        try:
            return _dump(autopilot.set_watchlist(db, tickers))
        except ValueError as e:
            return f"Not changed: {e}"


def list_ai_decisions(limit: int = 10) -> str:
    """The AI's most recent decisions with action, confidence, reasoning, stops and any executed order.

    Args:
        limit: How many to return (1-100).

    Returns:
        str: JSON list, newest first.
    """
    from api.services import autopilot
    with db_session() as db:
        return _dump(autopilot.decisions(db, limit))
