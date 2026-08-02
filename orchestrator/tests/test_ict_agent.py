"""
Unit & Integration tests for ICTAgent (Inner Circle Trader / Smart Money Concepts).
"""

import sys
import os
import asyncio
import pytest

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "TradingAgents"))

from orchestrator.tools.ict_tool import analyze_ict_concepts, ICTConfig
from orchestrator.sdk.ict_agent import ict_agent_handler
from orchestrator.guards.tv_execution_guard import TVExecutionGuard
from orchestrator.sdk.presets import create_trading_orchestrator


def test_analyze_ict_concepts_quantitative():
    """Test quantitative calculation of FVGs, OBs, Liquidity Sweeps, and OTE Fibs."""
    res = analyze_ict_concepts(ticker="BTCUSDT")
    assert isinstance(res, dict)
    assert res["ticker"] == "BTCUSDT"
    assert res["ict_bias"] in ["BULLISH", "BEARISH", "NEUTRAL"]
    assert "fair_value_gaps" in res
    assert "order_blocks" in res
    assert "liquidity_sweeps" in res
    assert "ote_zone" in res
    assert "fib_618" in res["ote_zone"]
    assert "fib_786" in res["ote_zone"]


def test_ict_agent_handler_execution():
    """Test ICTAgent handler integration with Orchestrator state manager."""
    orch = create_trading_orchestrator(ticker="BTCUSDT", topology="pipeline")
    report = asyncio.run(ict_agent_handler(orch.state, orch.bus, orch.tools, ticker="BTCUSDT"))

    assert report["ticker"] == "BTCUSDT"
    assert report["ict_bias"] in ["BULLISH", "BEARISH", "NEUTRAL"]

    # Verify report is saved to StateManager
    state_report = orch.state.get("analysis", "ict_report")
    assert state_report["ict_bias"] == report["ict_bias"]


def test_symmetric_ict_guard_matrix():
    """Test TVExecutionGuard symmetric Long and Short ICT conflict handling & position sizing multipliers."""
    guard = TVExecutionGuard()

    # 1. Long Conflict (BUY vs BEARISH ICT with HIGH OB) -> REQUIRE_CONFIRMATION & 0.50 Sizing
    res1 = guard.validate_execution(
        proposed_trade={"action": "BUY", "ticker": "BTCUSDT"},
        ta_recommendation="BUY",
        visual_confidence=0.80,
        ict_bias="BEARISH",
        ob_strength="HIGH",
    )
    assert res1["approved"] is False
    assert res1["action"] == "REQUIRE_CONFIRMATION"
    assert res1["sizing_multiplier"] == 0.50

    # 2. Long Conflict (BUY vs BEARISH ICT with MEDIUM OB) -> APPROVED (WARNING) & 0.75 Sizing
    res2 = guard.validate_execution(
        proposed_trade={"action": "BUY", "ticker": "BTCUSDT"},
        ta_recommendation="BUY",
        visual_confidence=0.80,
        ict_bias="BEARISH",
        ob_strength="MEDIUM",
    )
    assert res2["approved"] is True
    assert res2["action"] == "EXECUTE"
    assert res2["sizing_multiplier"] == 0.75

    # 3. Short Conflict (SELL vs BULLISH ICT with HIGH OB) -> REQUIRE_CONFIRMATION & 0.50 Sizing
    res3 = guard.validate_execution(
        proposed_trade={"action": "SELL", "ticker": "BTCUSDT"},
        ta_recommendation="SELL",
        visual_confidence=0.80,
        ict_bias="BULLISH",
        ob_strength="HIGH",
    )
    assert res3["approved"] is False
    assert res3["action"] == "REQUIRE_CONFIRMATION"
    assert res3["sizing_multiplier"] == 0.50

    # 4. Short Conflict (SELL vs BULLISH ICT with MEDIUM OB) -> APPROVED & 0.75 Sizing
    res4 = guard.validate_execution(
        proposed_trade={"action": "SELL", "ticker": "BTCUSDT"},
        ta_recommendation="SELL",
        visual_confidence=0.80,
        ict_bias="BULLISH",
        ob_strength="MEDIUM",
    )
    assert res4["approved"] is True
    assert res4["action"] == "EXECUTE"
    assert res4["sizing_multiplier"] == 0.75
