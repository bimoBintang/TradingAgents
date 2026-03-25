"""Tests for Phase 3 Guards & Safety components."""

import asyncio
import pytest

from orchestrator.guards.guardrails import GuardRails, Violation, Severity
from orchestrator.guards.token_meter import TokenMeter, BudgetExceeded
from orchestrator.guards.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitOpenError,
    KillSwitchError, DrawdownBreachedError,
)


# ── GuardRails Tests ──────────────────────────────────────────────────────────

class TestGuardRails:
    def setup_method(self):
        self.guard = GuardRails(allowed_tickers={"BTCUSDT", "ETHUSDT"})

    def test_valid_output_passes(self):
        result = self.guard.validate("analyst", {
            "action": "BUY", "ticker": "BTCUSDT", "confidence": 0.85
        })
        assert result.passed

    def test_invalid_ticker_blocked(self):
        result = self.guard.validate("analyst", {
            "action": "BUY", "ticker": "SCAMCOIN99", "confidence": 0.9
        })
        assert not result.passed
        rules = [v.rule for v in result.violations]
        assert "allowed_tickers" in rules

    def test_invalid_action_blocked(self):
        result = self.guard.validate("agent", {
            "action": "YOLO", "ticker": "BTCUSDT", "confidence": 0.7
        })
        assert not result.passed

    def test_confidence_out_of_range(self):
        result = self.guard.validate("agent", {
            "action": "BUY", "ticker": "BTCUSDT", "confidence": 1.5
        })
        assert not result.passed
        rules = [v.rule for v in result.violations]
        assert "confidence_range" in rules

    def test_empty_output_blocked(self):
        result = self.guard.validate("agent", None)
        assert not result.passed

    def test_loop_detection(self):
        for _ in range(3):
            self.guard.validate("loop_agent", {"action": "BUY", "confidence": 0.8})
        result = self.guard.validate("loop_agent", {"action": "BUY", "confidence": 0.8})
        rules = [v.rule for v in result.violations]
        assert "loop_detection" in rules

    def test_custom_rule(self):
        def no_hold_rule(output, agent_id, **_):
            if isinstance(output, dict) and output.get("action") == "HOLD":
                return Violation("no_hold", "HOLD not allowed", Severity.ERROR)
            return None
        self.guard.add_rule(no_hold_rule)
        result = self.guard.validate("agent", {"action": "HOLD", "confidence": 0.5})
        assert not result.passed

    def test_min_confidence_warning(self):
        guard = GuardRails(min_confidence=0.6)
        result = guard.validate("agent", {"action": "BUY", "confidence": 0.4})
        # Warning only, should still pass but have violations
        warnings = [v for v in result.violations if v.rule == "min_confidence"]
        assert len(warnings) == 1


# ── TokenMeter Tests ──────────────────────────────────────────────────────────

class TestTokenMeter:
    def setup_method(self):
        self.meter = TokenMeter(
            session_id="test-session",
            session_budget_usd=1.00,
            db_path=":memory:",
        )

    def test_record_and_cost(self):
        self.meter.record("analyst", input_tokens=1000, output_tokens=500)
        cost = self.meter.session_cost_usd
        assert cost > 0.0

    def test_token_tracking(self):
        self.meter.record("a", input_tokens=100, output_tokens=50)
        self.meter.record("b", input_tokens=200, output_tokens=100)
        tokens = self.meter.session_tokens
        assert tokens["input"] == 300
        assert tokens["output"] == 150

    def test_budget_not_exceeded(self):
        self.meter.record("agent", input_tokens=100, output_tokens=50)
        self.meter.check_budget()  # should not raise

    def test_budget_exceeded_raises(self):
        tiny_budget = TokenMeter(
            session_id="tiny", session_budget_usd=0.000001, db_path=":memory:"
        )
        tiny_budget.record("agent", input_tokens=10000, output_tokens=5000)
        with pytest.raises(BudgetExceeded):
            tiny_budget.check_budget()

    def test_by_agent_breakdown(self):
        self.meter.record("analyst_a", input_tokens=500, output_tokens=200)
        self.meter.record("analyst_b", input_tokens=300, output_tokens=100)
        usage = self.meter.get_by_agent("analyst_a")
        assert usage["input_tokens"] == 500
        assert usage["cost_usd"] > 0

    def test_top_spenders(self):
        self.meter.record("big_spender", input_tokens=5000, output_tokens=2000)
        self.meter.record("small_spender", input_tokens=100, output_tokens=50)
        spenders = self.meter.top_spenders(top_n=2)
        assert spenders[0]["agent_id"] == "big_spender"

    def test_summary(self):
        self.meter.record("agent", input_tokens=1000, output_tokens=500)
        s = self.meter.summary()
        assert "total_cost_usd" in s
        assert "budget_used_pct" in s


# ── CircuitBreaker Tests ──────────────────────────────────────────────────────

class TestCircuitBreaker:
    def setup_method(self):
        self.cb = CircuitBreaker(failure_threshold=3, reset_timeout=999)

    def test_closed_by_default(self):
        assert self.cb.get_state("agent_a") == CircuitState.CLOSED

    def test_successful_call(self):
        result = self.cb.call("agent_a", lambda: "ok")
        assert result == "ok"

    def test_opens_after_threshold(self):
        def failing():
            raise ValueError("fail")

        for _ in range(3):
            try:
                self.cb.call("failing_agent", failing)
            except ValueError:
                pass
        assert self.cb.get_state("failing_agent") == CircuitState.OPEN

    def test_open_circuit_raises(self):
        self.cb.force_open("blocked_agent", "test")
        with pytest.raises(CircuitOpenError):
            self.cb.call("blocked_agent", lambda: "ok")

    def test_manual_reset(self):
        self.cb.force_open("agent_b", "test")
        self.cb.reset("agent_b")
        assert self.cb.get_state("agent_b") == CircuitState.CLOSED

    def test_kill_switch(self):
        self.cb.kill("Emergency test")
        with pytest.raises(KillSwitchError):
            self.cb.call("any_agent", lambda: "ok")

    def test_revive_after_kill(self):
        self.cb.kill()
        self.cb.revive()
        result = self.cb.call("any_agent", lambda: 42)
        assert result == 42

    def test_drawdown_tracking(self):
        self.cb.record_pnl(1000.0)   # peak = 1000
        self.cb.record_pnl(-200.0)   # now at 800
        dd = self.cb.current_drawdown()
        assert dd == pytest.approx(-0.20)

    def test_drawdown_breach_raises(self):
        self.cb.record_pnl(1000.0)
        self.cb.record_pnl(-150.0)   # -15% drawdown
        with pytest.raises(DrawdownBreachedError):
            self.cb.check_drawdown(limit=-0.10)

    def test_drawdown_within_limit_passes(self):
        self.cb.record_pnl(1000.0)
        self.cb.record_pnl(-50.0)    # only -5%
        self.cb.check_drawdown(limit=-0.10)  # should NOT raise

    def test_async_call(self):
        async def async_fn():
            return "async_ok"

        result = asyncio.run(self.cb.async_call("async_agent", async_fn()))
        assert result == "async_ok"
