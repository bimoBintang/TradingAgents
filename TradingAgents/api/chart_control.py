"""Chart-control service — drives/reads a user's own dashboard chart
remotely (Fase 7 of the MCP integration).

Shared by api/routers/chart_control.py (REST, for parity/manual
testing) and mcp_server/tools_chart.py (MCP tools) — one implementation,
not two divergent copies, matching every other tool in this codebase.

Built entirely on infrastructure that already existed: the WS
ConnectionManager (api/ws_manager.py) that already pushes portfolio
updates, and ChartPanel.tsx's existing pattern-detection/price-line
mechanisms. No external dependency (no TradingView Desktop, no CDP) —
this is the user's OWN chart, driven over their OWN WebSocket
connection to OUR OWN backend, which is also why (unlike a CDP-based
approach) it works fine under the streamable-http remote transport too:
the MCP server process and the browser tab don't need to be on the
same machine, only both need to reach this backend.

Only semantically-scoped actions are exposed (set which ticker/
timeframe/indicator is shown, trigger pattern auto-detection, draw a
labelled price line) — no raw UI automation. See mcp_server/README.md.

State is ephemeral (in-memory, per-process) — it's "what's currently on
screen", not domain data, so it doesn't belong in the DB and resets on
backend restart (the dashboard re-reports its state on reconnect).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from api.ws_manager import manager

logger = logging.getLogger("api.chart_control")

_lock = threading.Lock()
_last_known_state: Dict[int, Dict[str, Any]] = {}

_NOT_CONNECTED = "Dashboard not connected — no open browser tab on /ws/chart-control."


def record_chart_state(user_id: int, state: Dict[str, Any]) -> None:
    """Called by the /ws/chart-control WS endpoint whenever the dashboard
    reports its current ticker/timeframe/indicator (on connect, and on
    every change)."""
    with _lock:
        _last_known_state[user_id] = state


def get_chart_state(user_id: int) -> Optional[Dict[str, Any]]:
    """Last state the dashboard reported, or None if it never has (not
    connected yet, or connected but hasn't reported since backend restart)."""
    with _lock:
        return _last_known_state.get(user_id)


async def set_chart_view(
    user_id: int,
    ticker: str,
    timeframe: Optional[str] = None,
    indicator: Optional[str] = None,
) -> Dict[str, Any]:
    """Change ticker/timeframe/indicator overlay on the user's dashboard chart."""
    if not manager.is_connected(user_id):
        return {"delivered": False, "reason": _NOT_CONNECTED}
    await manager.send_json(user_id, {
        "type": "chart_command",
        "action": "set_view",
        "ticker": ticker.upper(),
        "timeframe": timeframe,
        "indicator": indicator,
    })
    return {"delivered": True}


async def annotate_chart_patterns(user_id: int, ticker: str, timeframe: str = "1d") -> Dict[str, Any]:
    """Trigger chart-pattern auto-detection — same action as clicking
    ChartPanel's "Auto-Detect" button, invoked remotely."""
    if not manager.is_connected(user_id):
        return {"delivered": False, "reason": _NOT_CONNECTED}
    await manager.send_json(user_id, {
        "type": "chart_command",
        "action": "annotate_patterns",
        "ticker": ticker.upper(),
        "timeframe": timeframe,
    })
    return {"delivered": True}


async def highlight_price_level(
    user_id: int, ticker: str, price: float, label: str, color: str = "#f59e0b",
) -> Dict[str, Any]:
    """Draw a horizontal price-line annotation. Labelled with an "[AI]"
    prefix client-side so the user can tell it apart from their own
    manual drawings and clear them independently."""
    if not manager.is_connected(user_id):
        return {"delivered": False, "reason": _NOT_CONNECTED}
    await manager.send_json(user_id, {
        "type": "chart_command",
        "action": "highlight_price_level",
        "ticker": ticker.upper(),
        "price": price,
        "label": label,
        "color": color,
    })
    return {"delivered": True}


async def clear_ai_highlights(user_id: int, ticker: str) -> Dict[str, Any]:
    """Remove all AI-drawn price-line highlights for a ticker — leaves
    the user's own manual annotations untouched."""
    if not manager.is_connected(user_id):
        return {"delivered": False, "reason": _NOT_CONNECTED}
    await manager.send_json(user_id, {
        "type": "chart_command",
        "action": "clear_ai_highlights",
        "ticker": ticker.upper(),
    })
    return {"delivered": True}
