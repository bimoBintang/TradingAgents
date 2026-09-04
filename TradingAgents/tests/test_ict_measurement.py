"""Tests for the ICT/SMC detectors and their measurement harness.

Focused on the two things that made the previous ICT output untrustworthy:
FVG fill status resolved against an arbitrary bar, and structure computed
from fabricated candles.
"""

import pytest

from orchestrator.tools.ict_tool import (
    DEFAULT_ICT_CONFIG,
    analyze_ict_concepts,
    detect_fair_value_gaps,
)
from tradingagents.backtesting.ict_measurement import (
    FVGStats,
    measure_fvg_fill_rates,
    measure_order_block_performance,
)


class TestFVGFillTracking:
    """A gap's fill status must be resolved from the bars AFTER it formed."""

    def _series(self, ohlc):
        opens = [b[0] for b in ohlc]
        highs = [b[1] for b in ohlc]
        lows = [b[2] for b in ohlc]
        closes = [b[3] for b in ohlc]
        return opens, highs, lows, closes

    def test_detects_bullish_gap(self):
        # bar0 high=100, bar2 low=110 -> bullish gap 100..110
        o, h, l, c = self._series([
            (95, 100, 94, 99),
            (105, 112, 104, 110),
            (111, 118, 110, 115),
        ])
        fvgs = detect_fair_value_gaps(o, h, l, c)
        assert len(fvgs) == 1
        assert fvgs[0]["type"] == "BULLISH_FVG"
        assert fvgs[0]["gap_bottom"] == pytest.approx(100.0)
        assert fvgs[0]["gap_top"] == pytest.approx(110.0)

    def test_gap_filled_mid_series_is_not_reported_unfilled(self):
        # The gap (100..110) is fully filled at bar 3, then price runs far
        # away. The old implementation judged fill by the LAST bar only, so
        # it reported UNFILLED — the exact bug this pins down.
        o, h, l, c = self._series([
            (95, 100, 94, 99),
            (105, 112, 104, 110),
            (111, 118, 110, 115),
            (112, 114, 98, 100),      # <- fills the gap here
            (140, 160, 139, 155),     # <- price far above; last bar low=139
            (156, 170, 155, 168),
        ])
        fvgs = detect_fair_value_gaps(o, h, l, c)
        bullish = [f for f in fvgs if f["type"] == "BULLISH_FVG"][0]
        assert bullish["fill_status"] == "FULLY_FILLED"
        assert bullish["bars_to_full_fill"] == 1

    def test_genuinely_unfilled_gap_stays_unfilled(self):
        o, h, l, c = self._series([
            (95, 100, 94, 99),
            (105, 112, 104, 110),
            (111, 118, 110, 115),
            (116, 125, 115, 122),
            (123, 135, 122, 130),
        ])
        bullish = [f for f in detect_fair_value_gaps(o, h, l, c) if f["type"] == "BULLISH_FVG"][0]
        assert bullish["fill_status"] == "UNFILLED"
        assert bullish["bars_to_full_fill"] is None

    def test_partial_fill_at_consequent_encroachment(self):
        # Gap 100..110, CE midpoint = 105. Price dips to 106 only.
        o, h, l, c = self._series([
            (95, 100, 94, 99),
            (105, 112, 104, 110),
            (111, 118, 110, 115),
            (114, 116, 104.5, 112),   # touches below CE(105) but not 100
            (113, 120, 112, 118),
        ])
        bullish = [f for f in detect_fair_value_gaps(o, h, l, c) if f["type"] == "BULLISH_FVG"][0]
        assert bullish["fill_status"] == "PARTIALLY_FILLED"
        assert bullish["bars_to_partial_fill"] == 1
        assert bullish["bars_to_full_fill"] is None

    def test_bars_observed_is_reported(self):
        o, h, l, c = self._series([
            (95, 100, 94, 99),
            (105, 112, 104, 110),
            (111, 118, 110, 115),
            (116, 125, 115, 122),
        ])
        bullish = [f for f in detect_fair_value_gaps(o, h, l, c) if f["type"] == "BULLISH_FVG"][0]
        # Gap formed at index 2, series length 4 -> 1 bar observed after it.
        assert bullish["bars_observed"] == 1


class TestDataQualityReporting:
    """Consumers must be able to tell a real read from a placeholder."""

    def test_no_data_is_flagged_as_simulated(self):
        res = analyze_ict_concepts(ticker="BTCUSDT")
        assert res["data_quality"] == "SIMULATED_NO_DATA"
        assert res["warnings"], "a sine-wave result must carry a warning"

    def test_closes_only_is_flagged_as_synthetic(self):
        closes = [100.0 + i for i in range(30)]
        res = analyze_ict_concepts(ticker="BTCUSDT", prices=closes)
        assert res["data_quality"] == "SYNTHETIC_OHLC_FROM_CLOSES"
        assert res["warnings"]

    def test_real_ohlc_is_flagged_clean(self):
        n = 40
        closes = [100.0 + i for i in range(n)]
        opens = [c - 0.5 for c in closes]
        highs = [c + 1.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        res = analyze_ict_concepts(
            ticker="BTCUSDT", prices=closes, opens=opens, highs=highs, lows=lows
        )
        assert res["data_quality"] == "REAL_OHLC"
        assert res["warnings"] == []

    def test_mismatched_ohlc_lengths_fall_back_not_crash(self):
        closes = [100.0 + i for i in range(30)]
        res = analyze_ict_concepts(
            ticker="BTCUSDT", prices=closes, opens=closes, highs=closes[:5], lows=closes
        )
        assert res["data_quality"] == "SYNTHETIC_OHLC_FROM_CLOSES"


class TestFillRateMeasurement:
    def _fvg(self, to_full, to_partial, observed, type_="BULLISH_FVG"):
        return {
            "type": type_,
            "bars_to_full_fill": to_full,
            "bars_to_partial_fill": to_partial,
            "bars_observed": observed,
        }

    def test_censored_setups_are_excluded_not_counted_as_failures(self):
        # Two gaps: one genuinely unfilled with a full window, one that
        # simply has not had time yet. Counting the second as a miss would
        # understate the fill rate.
        fvgs = [
            self._fvg(None, None, 100),   # judged: unfilled
            self._fvg(None, None, 2),     # censored at horizon 20
        ]
        stats = measure_fvg_fill_rates(fvgs, horizons=[20])["BULLISH_FVG"][0]
        assert stats.sample_size == 1
        assert stats.excluded_censored == 1
        assert stats.full_fill_rate == 0.0

    def test_fill_inside_horizon_counts_even_with_short_window(self):
        # Outcome already known — no need for a full window.
        fvgs = [self._fvg(3, 2, 3)]
        stats = measure_fvg_fill_rates(fvgs, horizons=[20])["BULLISH_FVG"][0]
        assert stats.sample_size == 1
        assert stats.excluded_censored == 0
        assert stats.full_fill_rate == 100.0

    def test_fill_beyond_horizon_does_not_count(self):
        fvgs = [self._fvg(50, 40, 100)]
        stats = measure_fvg_fill_rates(fvgs, horizons=[20])["BULLISH_FVG"][0]
        assert stats.sample_size == 1
        assert stats.full_fill_count == 0

    def test_fill_rate_rises_with_horizon(self):
        fvgs = [self._fvg(t, t, 200) for t in (2, 8, 15, 45)]
        by_h = {s.horizon: s.full_fill_rate for s in measure_fvg_fill_rates(fvgs, [5, 10, 20, 60])["BULLISH_FVG"]}
        assert by_h[5] <= by_h[10] <= by_h[20] <= by_h[60]

    def test_median_time_to_fill(self):
        fvgs = [self._fvg(t, t, 200) for t in (1, 3, 5)]
        stats = measure_fvg_fill_rates(fvgs, horizons=[20])["BULLISH_FVG"][0]
        assert stats.median_bars_to_full_fill == 3

    def test_empty_input_is_safe(self):
        stats = measure_fvg_fill_rates([], horizons=[10])["BULLISH_FVG"][0]
        assert stats.sample_size == 0
        assert stats.full_fill_rate == 0.0


class TestOrderBlockMeasurement:
    def test_edge_is_measured_against_baseline_drift(self):
        # Steadily rising series: every bar has positive forward return, so
        # a bullish signal that merely rides the trend must show ~zero EDGE.
        closes = [100.0 * (1.01 ** i) for i in range(120)]
        obs = [
            {"type": "BULLISH_OB", "strength": "HIGH", "index": i}
            for i in range(10, 60, 10)
        ]
        stats = measure_order_block_performance(obs, closes, horizons=[10])[0]
        assert stats.mean_forward_return_pct > 0, "raw return is positive (drift)"
        assert abs(stats.edge_vs_baseline_pct) < 0.5, "but edge over baseline is ~zero"

    def test_bearish_block_return_is_sign_flipped(self):
        closes = [100.0 * (0.99 ** i) for i in range(120)]  # falling
        obs = [{"type": "BEARISH_OB", "strength": "HIGH", "index": i} for i in range(10, 60, 10)]
        stats = measure_order_block_performance(obs, closes, horizons=[10])[0]
        # A short in a falling market profits.
        assert stats.mean_forward_return_pct > 0

    def test_blocks_too_close_to_end_are_excluded(self):
        closes = [100.0 + i for i in range(50)]
        obs = [{"type": "BULLISH_OB", "strength": "HIGH", "index": 48}]
        stats = measure_order_block_performance(obs, closes, horizons=[10])[0]
        assert stats.sample_size == 0
        assert stats.excluded_censored == 1

    def test_empty_input_is_safe(self):
        assert measure_order_block_performance([], [100.0] * 50, horizons=[10]) == []
