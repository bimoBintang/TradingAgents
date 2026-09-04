"""Tests for realistic exit simulation in the backtester.

The backtester previously exited every trade at the next day's close,
ignoring stop_loss_pct / take_profit_pct / time_horizon entirely — so it
measured a strategy nobody actually runs. These tests pin down the exit
semantics so that can't silently regress, with particular attention to
the conservative choices (stop-before-target, gap fills) that keep the
simulation from flattering the strategy.
"""

import json

import pytest

from tradingagents.backtesting.backtest_runner import (
    Bar,
    _extract_decision,
    _simulate_exit,
)
from tradingagents.backtesting.metrics import TradeResult, calculate_metrics


def bar(date: str, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(date=date, open=o, high=h, low=l, close=c)


ENTRY = 100.0
FLAT = bar("d0", 100, 100, 100, 100)


class TestSimulateExitLong:
    def test_take_profit_hit(self):
        bars = [FLAT, bar("d1", 101, 105, 99, 104), bar("d2", 104, 112, 103, 111)]
        price, idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.05, 0.10, 5)
        assert reason == "take_profit"
        assert idx == 2
        assert price == pytest.approx(110.0)

    def test_stop_loss_hit(self):
        bars = [FLAT, bar("d1", 99, 100, 94, 96)]
        price, idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.05, 0.10, 5)
        assert reason == "stop_loss"
        assert idx == 1
        assert price == pytest.approx(95.0)

    def test_gap_through_stop_fills_at_open_not_stop_price(self):
        # Opens at 90, well below the 95 stop. A real stop does not hold
        # across a gap — filling at 95 would invent 5% of free profit.
        bars = [FLAT, bar("d1", 90, 92, 88, 91)]
        price, _idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.05, 0.10, 5)
        assert reason == "stop_loss"
        assert price == pytest.approx(90.0)

    def test_stop_wins_when_bar_spans_both_levels(self):
        # A daily bar hides the intrabar path; assume the worst branch.
        bars = [FLAT, bar("d1", 100, 115, 90, 105)]
        _price, _idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.05, 0.10, 5)
        assert reason == "stop_loss"

    def test_time_exit_at_horizon(self):
        bars = [FLAT] + [bar(f"d{i}", 100, 101, 99, 100 + i) for i in range(1, 8)]
        price, idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.20, 0.50, 3)
        assert reason == "time_exit"
        assert idx == 3
        assert price == pytest.approx(bars[3].close)

    def test_data_end_when_bars_run_out_before_horizon(self):
        bars = [FLAT, bar("d1", 100, 101, 99, 100.5)]
        _price, idx, reason = _simulate_exit(bars, 0, ENTRY, True, 0.20, 0.50, 10)
        assert reason == "data_end"
        assert idx == 1

    def test_no_bars_after_entry_returns_none(self):
        assert _simulate_exit([FLAT], 0, ENTRY, True, 0.05, 0.10, 5) is None

    def test_missing_stop_and_target_falls_through_to_time_exit(self):
        bars = [FLAT] + [bar(f"d{i}", 100, 200, 10, 150) for i in range(1, 4)]
        _price, _idx, reason = _simulate_exit(bars, 0, ENTRY, True, None, None, 2)
        assert reason == "time_exit"


class TestSimulateExitShort:
    def test_stop_is_above_entry(self):
        bars = [FLAT, bar("d1", 101, 106, 100, 105)]
        price, _idx, reason = _simulate_exit(bars, 0, ENTRY, False, 0.05, 0.10, 5)
        assert reason == "stop_loss"
        assert price == pytest.approx(105.0)

    def test_target_is_below_entry(self):
        bars = [FLAT, bar("d1", 99, 100, 89, 91)]
        price, _idx, reason = _simulate_exit(bars, 0, ENTRY, False, 0.05, 0.10, 5)
        assert reason == "take_profit"
        assert price == pytest.approx(90.0)

    def test_gap_through_short_stop_fills_at_open(self):
        bars = [FLAT, bar("d1", 112, 115, 110, 113)]
        price, _idx, reason = _simulate_exit(bars, 0, ENTRY, False, 0.05, 0.10, 5)
        assert reason == "stop_loss"
        assert price == pytest.approx(112.0)


class TestExtractDecision:
    def test_reads_confidence_score_not_confidence(self):
        # TradeDecision's field is `confidence_score`. Reading `confidence`
        # silently yielded the 0.5 default on every single trade, which
        # made all confidence-calibration reporting meaningless.
        spec = _extract_decision(json.dumps({"action": "BUY", "confidence_score": 0.92}))
        assert spec["confidence"] == pytest.approx(0.92)

    def test_falls_back_to_legacy_confidence_key(self):
        spec = _extract_decision(json.dumps({"action": "BUY", "confidence": 0.77}))
        assert spec["confidence"] == pytest.approx(0.77)

    def test_extracts_risk_parameters(self):
        spec = _extract_decision(json.dumps({
            "action": "SELL",
            "confidence_score": 0.8,
            "stop_loss_pct": 0.04,
            "take_profit_pct": 0.09,
            "quantity_pct": 0.15,
            "time_horizon": "medium_term",
        }))
        assert spec["action"] == "SELL"
        assert spec["stop_loss_pct"] == pytest.approx(0.04)
        assert spec["take_profit_pct"] == pytest.approx(0.09)
        assert spec["quantity_pct"] == pytest.approx(0.15)
        assert spec["time_horizon"] == "medium_term"

    def test_parses_json_with_nested_structures(self):
        # The old `\{[^{}]+\}` regex could not match anything nested.
        payload = json.dumps({
            "action": "BUY", "confidence_score": 0.6,
            "key_factors": ["a", "b"], "meta": {"nested": True},
        })
        spec = _extract_decision("Here is my call:\n" + payload + "\nDone.")
        assert spec["action"] == "BUY"
        assert spec["confidence"] == pytest.approx(0.6)

    def test_bare_text_fallback(self):
        assert _extract_decision("FINAL: SELL")["action"] == "SELL"
        assert _extract_decision("STRONG BUY here")["action"] == "STRONG_BUY"

    def test_empty_defaults_to_hold(self):
        assert _extract_decision(None)["action"] == "HOLD"
        assert _extract_decision("")["action"] == "HOLD"

    def test_quantity_pct_is_clamped(self):
        assert _extract_decision(json.dumps({"action": "BUY", "quantity_pct": 5.0}))["quantity_pct"] == 1.0
        assert _extract_decision(json.dumps({"action": "BUY", "quantity_pct": -2}))["quantity_pct"] == 0.0


class TestTradeResultAccounting:
    def test_short_profits_when_price_falls(self):
        t = TradeResult("d", "X", "SELL", 0.8, entry_price=100.0, exit_price=90.0)
        assert t.strategy_return_pct > 0
        assert t.direction_correct is True

    def test_costs_are_deducted(self):
        gross = TradeResult("d", "X", "BUY", 0.8, entry_price=100.0, exit_price=110.0)
        net = TradeResult("d", "X", "BUY", 0.8, entry_price=100.0, exit_price=110.0, cost_pct=0.3)
        assert net.strategy_return_pct == pytest.approx(gross.strategy_return_pct - 0.3)

    def test_allocation_scales_return_and_costs(self):
        full = TradeResult("d", "X", "BUY", 0.8, 100.0, 110.0, cost_pct=0.3, quantity_pct=1.0)
        tenth = TradeResult("d", "X", "BUY", 0.8, 100.0, 110.0, cost_pct=0.3, quantity_pct=0.1)
        assert tenth.strategy_return_pct == pytest.approx(full.strategy_return_pct * 0.1)

    def test_hold_is_neutral_and_scores_nothing(self):
        t = TradeResult("d", "X", "HOLD", 0.5, 100.0, 120.0)
        assert t.direction_correct is None
        assert t.strategy_return_pct == 0.0


class TestMetrics:
    def _trades(self, returns_pct):
        # Build trades whose price move produces the requested return.
        return [
            TradeResult(f"d{i}", "X", "BUY", 0.8, 100.0, 100.0 * (1 + r / 100.0), holding_days=1)
            for i, r in enumerate(returns_pct)
        ]

    def test_total_return_is_compounded_consistently_with_drawdown(self):
        m = calculate_metrics(self._trades([10.0, -10.0]))
        # +10% then -10% compounds to -1%, not 0% (a plain sum would say 0).
        assert m.total_return_pct == pytest.approx(-1.0, abs=1e-6)

    def test_max_drawdown_is_measured_from_peak(self):
        m = calculate_metrics(self._trades([20.0, -20.0]))
        assert m.max_drawdown_pct == pytest.approx(20.0, abs=1e-6)

    def test_sharpe_annualization_accounts_for_holding_period(self):
        # Identical return series, different holding periods: a strategy
        # holding 20 days has far fewer periods per year than one holding
        # 1 day, so it cannot claim the same annualized Sharpe.
        returns = [2.0, -1.0, 3.0, -0.5, 1.5, 0.5, -2.0, 2.5]
        daily = self._trades(returns)
        slow = self._trades(returns)
        for t in slow:
            t.holding_days = 20
        m_fast = calculate_metrics(daily)
        m_slow = calculate_metrics(slow)
        assert m_fast.sharpe_ratio > m_slow.sharpe_ratio

    def test_exit_reason_breakdown(self):
        trades = self._trades([1.0, -1.0, 2.0])
        trades[0].exit_reason = "stop_loss"
        trades[1].exit_reason = "take_profit"
        trades[2].exit_reason = "time_exit"
        m = calculate_metrics(trades)
        assert (m.stop_loss_exits, m.take_profit_exits, m.time_exits) == (1, 1, 1)

    def test_empty_trades_is_safe(self):
        m = calculate_metrics([])
        assert m.total_days == 0
        assert m.sharpe_ratio == 0.0
