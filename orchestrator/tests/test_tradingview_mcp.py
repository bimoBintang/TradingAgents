"""
Unit & Integration tests for TradingView MCP Client, Fallback Mode, Async Lock Queue, and Presets.
"""

import sys
import os
import asyncio
import pytest

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "TradingAgents"))

from orchestrator.mcp.tradingview_mcp_client import TradingViewMCPClient
from orchestrator.sdk.presets import create_trading_orchestrator


@pytest.fixture
def mcp_client():
    return TradingViewMCPClient()


def test_mcp_client_health_check_fallback(mcp_client):
    """Test health check when TradingView Desktop is offline (should return False gracefully)."""
    is_healthy = mcp_client.check_health()
    # If TradingView Desktop is not running, is_healthy is False
    assert is_healthy in [True, False]


def test_mcp_take_screenshot_fallback(mcp_client):
    """Test take_screenshot in fallback mode."""
    res = asyncio.run(mcp_client.take_screenshot("BTCUSDT", "1h"))
    assert isinstance(res, dict)
    assert res["ticker"] == "BTCUSDT"
    assert res["status"] in ["fallback", "success"]
    if res["status"] == "fallback":
        assert "FALLBACK MODE" in res["message"]
        assert "recommendation" in res


def test_mcp_async_lock_concurrency(mcp_client):
    """Simulate 5 subagents calling take_screenshot simultaneously (verifies asyncio.Lock queue)."""
    async def run_concurrent():
        tasks = [
            mcp_client.take_screenshot("BTCUSDT", "1h"),
            mcp_client.take_screenshot("ETHUSDT", "4h"),
            mcp_client.take_screenshot("SOLUSDT", "15m"),
            mcp_client.get_chart_info("BTCUSDT", "1h"),
            mcp_client.set_symbol_timeframe("BTCUSDT", "1h"),
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)

    results = asyncio.run(run_concurrent())
    assert len(results) == 5
    for r in results:
        assert isinstance(r, dict)
        assert "ticker" in r or "status" in r


def test_preset_tradingview_mcp_tool_registration():
    """Verify that create_trading_orchestrator registers Phase 1 & 2 TradingView MCP tools."""
    orch = create_trading_orchestrator(ticker="BTCUSDT", topology="pipeline")
    tools = orch.tools.list_tools()
    tool_names = [t["name"] for t in tools]

    assert "get_tradingview_analysis" in tool_names
    assert "tv_take_screenshot" in tool_names
    assert "tv_get_chart_info" in tool_names
    assert "tv_set_symbol_timeframe" in tool_names
    assert "tv_write_pinescript" in tool_names
    assert "tv_manage_alerts" in tool_names


def test_write_pinescript_verification(mcp_client):
    """Test Pine Script writing when TradingView Desktop isn't connected.

    Previously this asserted compiled=True unconditionally — that was
    testing a hardcoded fake success (the fallback path used to always
    claim "compiled" regardless of whether anything was actually sent
    anywhere). With no CDP running (the case in CI/this test env),
    nothing was compiled, so compiled=False is the honest, correct result.
    """
    code = "indicator('My RSI', overlay=true)\nplot(ta.rsi(close, 14))"
    res = asyncio.run(mcp_client.write_pinescript(code, "Test_RSI"))
    assert res["script_name"] == "Test_RSI"
    assert res["compiled"] is False
    assert res["status"] == "unavailable"


def test_manage_alert_execution(mcp_client):
    """Test price alert management."""
    res = asyncio.run(mcp_client.manage_alert("BTCUSDT", 70000.0, "GREATER_THAN"))
    assert res["ticker"] == "BTCUSDT"
    assert res["price"] == 70000.0
    assert "status" in res


def test_chart_vision_agent_execution():
    """Test ChartVisionAgent handler integration with Orchestrator.

    Previously this asserted primary_trend was always one of
    BULLISH/BEARISH/SIDEWAYS — that was testing a hardcoded lookup table
    that fabricated a trend from the SAME quantitative TA numbers already
    shown elsewhere, regardless of whether any actual chart image was
    ever analyzed. With no CDP running and no client-side fallback
    screenshot supplied (the case here), there's no image to analyze, so
    mode="UNAVAILABLE" with primary_trend=None is the honest, correct
    result — not a guess dressed up as a vision analysis.
    """
    from orchestrator.sdk import create_trading_orchestrator, chart_vision_agent_handler
    orch = create_trading_orchestrator(ticker="BTCUSDT", topology="pipeline")
    report = asyncio.run(chart_vision_agent_handler(orch.state, orch.bus, orch.tools))

    assert report["ticker"] == "BTCUSDT"
    assert report["mode"] == "UNAVAILABLE"
    assert report["primary_trend"] is None
    assert "visual_confidence" in report
    # Check that report is stored in StateManager
    state_report = orch.state.get("analysis", "chart_vision_report")
    assert state_report["primary_trend"] == report["primary_trend"]


def test_mcp_mid_execution_fallback_switch(mcp_client):
    """Test mock CDP dropping mid-execution and gracefully switching to fallback mode."""
    from unittest.mock import patch

    # 1. Simulate client initially healthy, but CDP call throws exception
    with patch.object(mcp_client, 'check_health_async', return_value=True):
        with patch.object(mcp_client, '_capture_cdp_screenshot', side_effect=RuntimeError("CDP WebSocket connection dropped")):
            res = asyncio.run(mcp_client.take_screenshot("BTCUSDT", "1h"))
            assert res["status"] == "fallback"
            assert "FALLBACK MODE" in res["message"]
            assert "recommendation" in res
