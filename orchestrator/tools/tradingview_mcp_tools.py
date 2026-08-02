"""
TradingView MCP Tools Provider for CMAOP Orchestrator.

Exposes Phase 1 TradingView Desktop MCP tools (screenshot, chart info, symbol navigation)
with automatic fallback mode and async lock protection.
"""

import asyncio
import concurrent.futures
from typing import Any, Dict
from orchestrator.sdk import tool
from orchestrator.mcp.tradingview_mcp_client import TradingViewMCPClient

# Shared Client Instance
_MCP_CLIENT = TradingViewMCPClient()


def _run_async(coro):
    """Safely run async coroutine whether an event loop is running or not."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


@tool(
    name="tv_take_screenshot",
    category="chart_visual",
    description="Capture live chart screenshot from TradingView Desktop (or fallback to quantitative TA signals if desktop is offline).",
)
def tv_take_screenshot(
    ticker: str,
    timeframe: str = "1h",
) -> Dict[str, Any]:
    """
    Capture a compressed chart screenshot for Multimodal LLM Vision analysis.
    """
    return _run_async(_MCP_CLIENT.take_screenshot(ticker=ticker, timeframe=timeframe))


@tool(
    name="tv_get_chart_info",
    category="chart_visual",
    description="Retrieve active chart indicators, symbol, and timeframe from TradingView Desktop or fallback provider.",
)
def tv_get_chart_info(
    ticker: str = "BTCUSDT",
    timeframe: str = "1h",
) -> Dict[str, Any]:
    """
    Get active chart info and indicator metadata.
    """
    return _run_async(_MCP_CLIENT.get_chart_info(ticker=ticker, timeframe=timeframe))


@tool(
    name="tv_set_symbol_timeframe",
    category="chart_visual",
    description="Navigate active TradingView Desktop tab to a new symbol and timeframe.",
)
def tv_set_symbol_timeframe(
    ticker: str,
    timeframe: str = "1h",
) -> Dict[str, Any]:
    """
    Navigate active TradingView Desktop chart tab.
    """
    return _run_async(_MCP_CLIENT.set_symbol_timeframe(ticker=ticker, timeframe=timeframe))


@tool(
    name="tv_write_pinescript",
    category="strategy",
    description="Write, inject, and verify Pine Script indicator or strategy code in TradingView Desktop Pine Editor.",
)
def tv_write_pinescript(
    code: str,
    script_name: str = "CMAOP_Strategy",
) -> Dict[str, Any]:
    """
    Inject and verify Pine Script in TradingView Desktop editor.
    """
    return _run_async(_MCP_CLIENT.write_pinescript(code=code, script_name=script_name))


@tool(
    name="tv_manage_alerts",
    category="alerts",
    description="Create or manage price alert notifications in TradingView Desktop or virtual alert queue.",
)
def tv_manage_alerts(
    ticker: str,
    price: float,
    condition: str = "GREATER_THAN",
) -> Dict[str, Any]:
    """
    Add or update price alert rule.
    """
    return _run_async(_MCP_CLIENT.manage_alert(ticker=ticker, price=price, condition=condition))
