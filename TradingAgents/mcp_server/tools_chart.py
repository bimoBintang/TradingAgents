"""Chart-control MCP tools — Fase 7.

Reads/drives the user's OWN dashboard chart (OverviewPage/ChartPanel.tsx)
over the existing WebSocket infrastructure (api/chart_control.py,
api/ws_manager.py) — same reuse-not-duplicate pattern as every other
tool file in this MCP server. No external dependency (no TradingView
Desktop app, no Chrome DevTools Protocol) — this is our own chart, our
own data, our own WebSocket, which is also why it works fine under the
streamable-http remote transport (Fase 4): the MCP server process and
the user's browser tab don't need to share a machine, only both need
to reach the backend.

Requires the user's dashboard to have an open, connected browser tab
(the /ws/chart-control WS channel) — there's nothing to control if no
chart is open. Every tool here degrades gracefully (returns a clear
"not connected" message) rather than raising when that's the case.

Scope: only semantically-scoped, read/annotate actions are exposed —
change ticker/timeframe/indicator, trigger pattern auto-detection, draw
a labelled price line, clear those labels. Deliberately NOT exposed:
raw UI automation (click/keyboard/screenshot at pixel coordinates) —
see mcp_server/README.md for the reasoning. There's also nothing here
resembling trade execution; this file only ever touches what's
*displayed*, never portfolio/order state (see tools_trading.py for that,
with its own separate approval guardrail).
"""

from __future__ import annotations

from typing import Optional

from api import chart_control as service
from mcp_server.context import db_session, resolve_mcp_user


def _current_user_id() -> int:
    with db_session() as db:
        return resolve_mcp_user(db).id


def get_chart_state() -> str:
    """Get what the user's dashboard chart is currently showing: ticker,
    timeframe, and active indicator overlay — as last reported by their
    browser tab.

    Returns:
        str: Current chart state, or a message if no dashboard is connected.
    """
    state = service.get_chart_state(_current_user_id())
    if not state:
        return "No dashboard chart is currently connected/reporting state."
    return (
        f"Ticker: {state.get('ticker', 'N/A')}\n"
        f"Timeframe: {state.get('timeframe', 'N/A')}\n"
        f"Active indicator overlay: {state.get('activeIndicator', 'N/A')}"
    )


async def set_chart_view(
    ticker: str, timeframe: Optional[str] = None, indicator: Optional[str] = None,
) -> str:
    """Change what the user's dashboard chart is showing: ticker,
    timeframe, and/or which indicator overlay is active. Requires their
    dashboard to be open with an active connection.

    Args:
        ticker: Ticker to switch the chart to, e.g. AAPL, BTC-USD.
        timeframe: One of 1D, 1H, 30M, 15M, 5M. Leave unset to keep current.
        indicator: One of ChartPanel's indicator options (e.g. 'sma', 'bb',
            'rsi', 'fib', 'smc', 'all', 'none'). Leave unset to keep current.

    Returns:
        str: Confirmation, or a message if the dashboard isn't connected.
    """
    result = await service.set_chart_view(_current_user_id(), ticker, timeframe, indicator)
    if not result["delivered"]:
        return f"Could not update chart: {result['reason']}"
    parts = [ticker.upper()]
    if timeframe:
        parts.append(timeframe)
    if indicator:
        parts.append(f"indicator={indicator}")
    return f"Chart updated: {' | '.join(parts)}"


async def annotate_chart_patterns(ticker: str, timeframe: str = "1d") -> str:
    """Trigger chart-pattern auto-detection (head & shoulders, rising/
    falling wedges) on the user's dashboard chart and draw the results —
    the same action as clicking ChartPanel's "Auto-Detect" button,
    triggered remotely.

    Args:
        ticker: Ticker to detect patterns for.
        timeframe: Chart interval, e.g. 1d, 1h, 30m, 15m, 5m.

    Returns:
        str: Confirmation, or a message if the dashboard isn't connected.
    """
    result = await service.annotate_chart_patterns(_current_user_id(), ticker, timeframe)
    if not result["delivered"]:
        return f"Could not annotate chart: {result['reason']}"
    return f"Pattern detection triggered on {ticker.upper()}'s chart ({timeframe})."


async def highlight_price_level(ticker: str, price: float, label: str) -> str:
    """Draw a horizontal price-line annotation on the user's dashboard
    chart — e.g. to mark a support/resistance level found during
    analysis. Rendered with an "[AI]" prefix client-side so the user can
    tell it apart from their own manual annotations, and clear it
    separately with clear_ai_highlights.

    Args:
        ticker: Ticker whose chart to annotate (should be the one currently shown).
        price: Price level to draw the line at.
        label: Short label for the line, e.g. "Support" or "Entry target".

    Returns:
        str: Confirmation, or a message if the dashboard isn't connected.
    """
    result = await service.highlight_price_level(_current_user_id(), ticker, price, label)
    if not result["delivered"]:
        return f"Could not highlight price level: {result['reason']}"
    return f"Highlighted ${price:,.2f} ('{label}') on {ticker.upper()}'s chart."


async def clear_ai_highlights(ticker: str) -> str:
    """Remove all AI-drawn price-line highlights (from highlight_price_level)
    on the user's dashboard chart for a ticker. Leaves the user's own
    manual annotations untouched.

    Args:
        ticker: Ticker whose AI highlights to clear.

    Returns:
        str: Confirmation, or a message if the dashboard isn't connected.
    """
    result = await service.clear_ai_highlights(_current_user_id(), ticker)
    if not result["delivered"]:
        return f"Could not clear highlights: {result['reason']}"
    return f"Cleared AI highlights on {ticker.upper()}'s chart."
