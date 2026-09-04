"""Empirical measurement of the ICT / Smart Money Concepts engine.

WHY
---
The ICT engine's output (ict_bias) is read by the LLM agents as evidence,
and is the intended input to TVExecutionGuard's conflict matrix (that
guard is not currently wired into any execution path). Either way the
signal has never been earned with evidence — the widely repeated "FVGs
fill ~70% of the time" figure comes from small independent backtests, not
from this codebase's own detectors on this codebase's own data.

This module measures the ACTUAL detectors in orchestrator/tools/ict_tool.py
against real OHLC, and answers three questions that decide whether the
signal deserves to size positions:

  1. What fraction of detected FVGs actually fill, at what horizon?
  2. Does Order Block "HIGH" strength predict better forward returns than
     "MEDIUM" — and do either beat simply being long?
  3. How long does a fill take, when it happens?

TWO METHODOLOGY TRAPS THIS AVOIDS
---------------------------------
**Censoring.** A gap formed 3 bars before the data ends has had almost no
chance to fill. Counting it as "unfilled" drags the measured rate down
toward zero as you shorten the sample. Every statistic here is computed
only over setups with a full observation window (`bars_observed >= horizon`),
and reports how many were excluded.

**No baseline = no information.** "Bullish order blocks returned +0.8%
over 10 bars" is meaningless in a market that returned +0.9% over every
random 10-bar window. Order block stats are always reported against the
unconditional forward return of the same series, so the number you read
is edge, not drift.
"""

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Horizons (in bars) at which fill rates are reported.
DEFAULT_HORIZONS = (5, 10, 20, 60)


@dataclass
class FVGStats:
    """Fill statistics for one FVG category at one horizon."""
    horizon: int
    sample_size: int = 0             # setups with a full observation window
    excluded_censored: int = 0       # setups too close to the data end to judge
    full_fill_count: int = 0
    partial_fill_count: int = 0
    full_fill_rate: float = 0.0      # percent
    partial_fill_rate: float = 0.0   # percent
    median_bars_to_full_fill: Optional[float] = None


@dataclass
class OrderBlockStats:
    """Forward-return statistics for order blocks of one strength."""
    strength: str
    horizon: int
    sample_size: int = 0
    excluded_censored: int = 0
    mean_forward_return_pct: float = 0.0
    median_forward_return_pct: float = 0.0
    win_rate_pct: float = 0.0
    # The null hypothesis: the same forward return measured over every bar,
    # regardless of signal. Edge is the difference, not the raw number.
    baseline_mean_return_pct: float = 0.0
    edge_vs_baseline_pct: float = 0.0


@dataclass
class ICTMeasurementResult:
    ticker: str
    start_date: str
    end_date: str
    total_bars: int = 0
    data_quality: str = "REAL_OHLC"
    fvg_total_detected: int = 0
    order_blocks_total_detected: int = 0
    liquidity_sweeps_detected: int = 0
    fvg_stats: Dict[str, List[FVGStats]] = field(default_factory=dict)
    ob_stats: List[OrderBlockStats] = field(default_factory=list)


def _forward_return_pct(closes: Sequence[float], idx: int, horizon: int, is_long: bool) -> Optional[float]:
    """Signed forward return from bar `idx` to bar `idx + horizon`."""
    end = idx + horizon
    if end >= len(closes) or closes[idx] <= 0:
        return None
    raw = (closes[end] - closes[idx]) / closes[idx] * 100.0
    return raw if is_long else -raw


def _baseline_forward_returns(closes: Sequence[float], horizon: int, is_long: bool) -> List[float]:
    """Unconditional forward returns over every bar — the null to beat."""
    out: List[float] = []
    for i in range(len(closes) - horizon):
        r = _forward_return_pct(closes, i, horizon, is_long)
        if r is not None:
            out.append(r)
    return out


def measure_fvg_fill_rates(
    fvgs: List[Dict[str, Any]],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> Dict[str, List[FVGStats]]:
    """Fill rates per FVG type, per horizon, with censoring control.

    Relies on `bars_to_full_fill` / `bars_to_partial_fill` / `bars_observed`
    from detect_fair_value_gaps(). Those fields only became trustworthy
    once that function stopped judging every gap against the final bar of
    the series — see its docstring.
    """
    results: Dict[str, List[FVGStats]] = {}

    for fvg_type in ("BULLISH_FVG", "BEARISH_FVG"):
        subset = [f for f in fvgs if f.get("type") == fvg_type]
        per_horizon: List[FVGStats] = []

        for horizon in horizons:
            stats = FVGStats(horizon=horizon)
            fill_times: List[int] = []

            for f in subset:
                observed = f.get("bars_observed", 0)
                to_full = f.get("bars_to_full_fill")
                to_partial = f.get("bars_to_partial_fill")

                # A gap that filled inside the horizon counts even if the
                # window is short — the outcome is already known. Only
                # UNfilled gaps need a full window to be judged.
                filled_in_horizon = to_full is not None and to_full <= horizon
                if not filled_in_horizon and observed < horizon:
                    stats.excluded_censored += 1
                    continue

                stats.sample_size += 1
                if filled_in_horizon:
                    stats.full_fill_count += 1
                    fill_times.append(to_full)
                if to_partial is not None and to_partial <= horizon:
                    stats.partial_fill_count += 1

            if stats.sample_size > 0:
                stats.full_fill_rate = stats.full_fill_count / stats.sample_size * 100.0
                stats.partial_fill_rate = stats.partial_fill_count / stats.sample_size * 100.0
            if fill_times:
                stats.median_bars_to_full_fill = statistics.median(fill_times)

            per_horizon.append(stats)

        results[fvg_type] = per_horizon

    return results


def measure_order_block_performance(
    obs: List[Dict[str, Any]],
    closes: Sequence[float],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> List[OrderBlockStats]:
    """Forward returns after each order block, split by strength, vs baseline.

    A bullish OB is treated as a long signal and a bearish OB as a short
    signal, entered at the block's own bar close. The question is not
    "did it go up" but "did it go up MORE than an arbitrary bar would
    have" — hence baseline_mean_return_pct on every row.
    """
    results: List[OrderBlockStats] = []

    for strength in ("HIGH", "MEDIUM"):
        for ob_type, is_long in (("BULLISH_OB", True), ("BEARISH_OB", False)):
            subset = [
                o for o in obs
                if o.get("strength") == strength and o.get("type") == ob_type
            ]
            if not subset:
                continue

            for horizon in horizons:
                stats = OrderBlockStats(strength=f"{strength} {ob_type}", horizon=horizon)
                returns: List[float] = []

                for o in subset:
                    idx = o.get("index")
                    if idx is None:
                        continue
                    r = _forward_return_pct(closes, idx, horizon, is_long)
                    if r is None:
                        stats.excluded_censored += 1
                        continue
                    returns.append(r)

                if not returns:
                    results.append(stats)
                    continue

                baseline = _baseline_forward_returns(closes, horizon, is_long)
                stats.sample_size = len(returns)
                stats.mean_forward_return_pct = sum(returns) / len(returns)
                stats.median_forward_return_pct = statistics.median(returns)
                stats.win_rate_pct = sum(1 for r in returns if r > 0) / len(returns) * 100.0
                stats.baseline_mean_return_pct = (
                    sum(baseline) / len(baseline) if baseline else 0.0
                )
                stats.edge_vs_baseline_pct = (
                    stats.mean_forward_return_pct - stats.baseline_mean_return_pct
                )
                results.append(stats)

    return results


def measure_ict_on_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> ICTMeasurementResult:
    """Run the real ICT detectors over real OHLC and measure them.

    Args:
        ticker: Symbol (yfinance convention, e.g. "BTC-USD", "NVDA").
        start_date / end_date: YYYY-MM-DD.
        horizons: Bar counts at which to evaluate fills and forward returns.
    """
    from orchestrator.tools.ict_tool import (
        DEFAULT_ICT_CONFIG,
        calculate_atr,
        detect_fair_value_gaps,
        detect_liquidity_sweeps,
        detect_order_blocks,
    )
    from .backtest_runner import _fetch_bars

    bars = _fetch_bars(ticker, start_date, end_date, lookahead_days=0)
    result = ICTMeasurementResult(
        ticker=ticker, start_date=start_date, end_date=end_date, total_bars=len(bars)
    )
    if len(bars) < 30:
        logger.error("Not enough bars for %s to measure ICT (%d)", ticker, len(bars))
        return result

    opens = [b.open for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]

    cfg = DEFAULT_ICT_CONFIG
    atr = calculate_atr(highs, lows, closes, period=14)

    fvgs = detect_fair_value_gaps(opens, highs, lows, closes, cfg)
    obs = detect_order_blocks(opens, highs, lows, closes, atr, cfg)
    sweeps = detect_liquidity_sweeps(highs, lows, closes, cfg)

    result.fvg_total_detected = len(fvgs)
    result.order_blocks_total_detected = len(obs)
    result.liquidity_sweeps_detected = len(sweeps)
    result.fvg_stats = measure_fvg_fill_rates(fvgs, horizons)
    result.ob_stats = measure_order_block_performance(obs, closes, horizons)

    return result


def format_measurement_report(result: ICTMeasurementResult) -> str:
    """Render an ICT measurement result as markdown."""
    lines = [
        f"# ICT / SMC Empirical Measurement — {result.ticker}",
        f"**Period**: {result.start_date} → {result.end_date} ({result.total_bars} bars)",
        "",
        "Measured with the production detectors in `orchestrator/tools/ict_tool.py`,",
        "on real OHLC. Setups without a full observation window are excluded, not",
        "counted as failures.",
        "",
        "| Detected | Count |",
        "|---|---|",
        f"| Fair Value Gaps | {result.fvg_total_detected} |",
        f"| Order Blocks | {result.order_blocks_total_detected} |",
        f"| Liquidity Sweeps (last bar) | {result.liquidity_sweeps_detected} |",
        "",
        "## FVG Fill Rates",
        "",
        "| Type | Horizon | n | Excluded | Full Fill | 50% CE Fill | Median Bars to Fill |",
        "|---|---|---|---|---|---|---|",
    ]

    for fvg_type, stats_list in result.fvg_stats.items():
        for s in stats_list:
            median = f"{s.median_bars_to_full_fill:.0f}" if s.median_bars_to_full_fill else "—"
            lines.append(
                f"| {fvg_type} | {s.horizon} bars | {s.sample_size} | {s.excluded_censored} "
                f"| **{s.full_fill_rate:.1f}%** | {s.partial_fill_rate:.1f}% | {median} |"
            )

    lines += [
        "",
        "## Order Block Forward Returns",
        "",
        "`Edge` is the mean forward return MINUS the unconditional forward return",
        "of the same series. A positive raw return with ~zero edge means the signal",
        "captured market drift, not information.",
        "",
        "| Block | Horizon | n | Mean | Baseline | **Edge** | Win Rate |",
        "|---|---|---|---|---|---|---|",
    ]

    for s in result.ob_stats:
        if s.sample_size == 0:
            continue
        lines.append(
            f"| {s.strength} | {s.horizon} bars | {s.sample_size} "
            f"| {s.mean_forward_return_pct:+.2f}% | {s.baseline_mean_return_pct:+.2f}% "
            f"| **{s.edge_vs_baseline_pct:+.2f}%** | {s.win_rate_pct:.1f}% |"
        )

    # Interpretation — the reason to run this at all is the decision it
    # supports, so state it rather than leaving a table to be squinted at.
    lines += ["", "## Interpretation", ""]
    high = [s for s in result.ob_stats if s.strength.startswith("HIGH") and s.sample_size >= 10]
    medium = [s for s in result.ob_stats if s.strength.startswith("MEDIUM") and s.sample_size >= 10]
    if high and medium:
        high_edge = sum(s.edge_vs_baseline_pct for s in high) / len(high)
        med_edge = sum(s.edge_vs_baseline_pct for s in medium) / len(medium)
        if high_edge > med_edge > 0:
            lines.append(
                f"- HIGH-strength blocks show more edge than MEDIUM "
                f"({high_edge:+.2f}% vs {med_edge:+.2f}%), which is what the displacement-ratio "
                "threshold is supposed to buy. Worth keeping as a sizing input."
            )
        else:
            lines.append(
                f"- HIGH-strength blocks do NOT show more edge than MEDIUM "
                f"({high_edge:+.2f}% vs {med_edge:+.2f}%). The displacement threshold is not "
                "separating signal from noise on this data — do not let strength drive sizing."
            )
    else:
        lines.append(
            "- Too few order blocks (n < 10 per bucket) to say anything. Widen the period "
            "before drawing conclusions; this is a sample-size problem, not a result."
        )

    lines.append(
        "- Compare the FVG fill rates above against the commonly cited ~70% figure. "
        "If they disagree, YOUR data is the one that matters — that number was never "
        "validated on this instrument, timeframe, or detector implementation."
    )

    return "\n".join(lines)
