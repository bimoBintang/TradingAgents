"""
Unit & Integration tests for Phase 4: TVExecutionGuard, Backtesting Engine, and CLI Extensions.
"""

import sys
import os
import time
import pytest

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _root)
sys.path.insert(0, os.path.join(_root, "TradingAgents"))

from orchestrator.guards.tv_execution_guard import TVExecutionGuard
from tradingagents.execution.tv_backtest import run_tv_backtest, BACKTEST_DISCLAIMER
from orchestrator.cli.orchctl import main as orchctl_main


@pytest.fixture
def execution_guard():
    return TVExecutionGuard(min_confidence_threshold=0.60, confirmation_timeout_seconds=60.0, fail_closed=True)


def test_tv_execution_guard_approved(execution_guard):
    """Test TVExecutionGuard approves valid trade when signals align."""
    proposed_trade = {"action": "BUY", "ticker": "BTCUSDT"}
    res = execution_guard.validate_execution(
        proposed_trade=proposed_trade,
        ta_recommendation="BUY",
        visual_confidence=0.85,
        cdp_healthy=True,
        data_complete=True,
    )
    assert res["approved"] is True
    assert res["action"] == "EXECUTE"


def test_tv_execution_guard_fail_closed(execution_guard):
    """Test TVExecutionGuard triggers Fail-Closed when data is incomplete."""
    proposed_trade = {"action": "BUY", "ticker": "BTCUSDT"}
    res = execution_guard.validate_execution(
        proposed_trade=proposed_trade,
        ta_recommendation=None,
        visual_confidence=None,
        cdp_healthy=False,
        data_complete=False,
    )
    assert res["approved"] is False
    assert res["action"] == "REQUIRE_CONFIRMATION"
    assert "Fail-Closed" in res["reason"]


def test_tv_execution_guard_signal_conflict(execution_guard):
    """Test TVExecutionGuard rejects BUY trade when TradingView TA is STRONG_SELL."""
    proposed_trade = {"action": "BUY", "ticker": "BTCUSDT"}
    res = execution_guard.validate_execution(
        proposed_trade=proposed_trade,
        ta_recommendation="STRONG_SELL",
        visual_confidence=0.80,
        cdp_healthy=True,
        data_complete=True,
    )
    assert res["approved"] is False
    assert res["action"] == "REJECT"
    assert "Signal Conflict" in res["reason"]


def test_tv_execution_guard_low_confidence(execution_guard):
    """Test TVExecutionGuard rejects trade when visual confidence < 0.60 threshold."""
    proposed_trade = {"action": "BUY", "ticker": "BTCUSDT"}
    res = execution_guard.validate_execution(
        proposed_trade=proposed_trade,
        ta_recommendation="BUY",
        visual_confidence=0.45,  # Below 0.60
        cdp_healthy=True,
        data_complete=True,
    )
    assert res["approved"] is False
    assert res["action"] == "REJECT"
    assert "Low Visual Confidence" in res["reason"]


def test_tv_execution_guard_order_timeout(execution_guard):
    """Test 60-second order confirmation expiration timeout."""
    past_timestamp = time.time() - 65.0  # 65 seconds ago
    assert execution_guard.is_order_expired(past_timestamp) is True

    recent_timestamp = time.time() - 10.0  # 10 seconds ago
    assert execution_guard.is_order_expired(recent_timestamp) is False


def test_tv_backtest_simulation():
    """Test backtesting engine performance metrics calculation."""
    res = run_tv_backtest(ticker="BTCUSDT", initial_cash=10000.0, timeframe="1h")
    assert isinstance(res, dict)
    assert res["ticker"] == "BTCUSDT"
    assert "win_rate" in res
    assert "total_return_pct" in res
    assert "max_drawdown_pct" in res
    assert "sharpe_ratio" in res
    assert res["disclaimer"] == BACKTEST_DISCLAIMER


def test_cli_tv_status_command(capsys):
    """Test running orchctl tv-status CLI command."""
    orchctl_main(["tv-status"])
    captured = capsys.readouterr()
    assert "TradingView Telemetry & CDP Status" in captured.out
    assert "FAIL-CLOSED" in captured.out


def test_circuit_breaker_triggers_and_manual_reset():
    """Test CircuitBreaker failure threshold, drawdown breach, and manual reset policy."""
    from orchestrator.guards.circuit_breaker import CircuitBreaker, CircuitOpenError, DrawdownBreachedError, KillSwitchError

    cb = CircuitBreaker(failure_threshold=3, reset_timeout=60.0)

    # 1. Agent Failure Threshold (N = 3 Fails) -> Circuit OPEN
    def failing_func():
        raise ValueError("API Failure")

    for _ in range(3):
        with pytest.raises(ValueError):
            cb.call("tradingview_mcp", failing_func)

    assert cb.is_open("tradingview_mcp") is True

    # 4th call raises CircuitOpenError
    with pytest.raises(CircuitOpenError):
        cb.call("tradingview_mcp", failing_func)

    # Manual Reset restores circuit
    cb.reset("tradingview_mcp")
    assert cb.is_open("tradingview_mcp") is False

    # 2. Portfolio Drawdown Breached (-15% loss) -> DrawdownBreachedError
    cb.record_pnl(1000.0)  # Peak PnL = $1000
    cb.record_pnl(-200.0)  # Current PnL = $800 (Drawdown = -20%)
    with pytest.raises(DrawdownBreachedError):
        cb.check_drawdown(limit=-0.15)

    # 3. Global Emergency Kill Switch -> KillSwitchError
    cb.kill("Emergency stop activated")
    with pytest.raises(KillSwitchError):
        cb.call("tradingview_mcp", lambda: True)

    cb.revive()  # Manual revive restores normal operation
    assert cb.call("tradingview_mcp", lambda: True) is True


def test_wilders_rsi_calculation_alignment():
    """Test Wilder's RSI calculation helper against known boundary conditions."""
    from tradingagents.execution.tv_backtest import calculate_wilders_rsi

    prices = [100.0 + i for i in range(30)]  # Strictly rising prices
    rsi_vals = calculate_wilders_rsi(prices, period=14)
    assert rsi_vals[-1] == 100.0  # Perfect uptrend gives RSI 100

    falling_prices = [100.0 - i for i in range(30)]  # Strictly falling prices
    rsi_falling = calculate_wilders_rsi(falling_prices, period=14)
    assert rsi_falling[-1] < 1.0  # Downtrend gives RSI near 0
