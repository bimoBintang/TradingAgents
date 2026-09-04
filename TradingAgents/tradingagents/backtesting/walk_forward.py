"""Walk-forward analysis — the honest way to validate a parameterized strategy.

WHY NOT JUST BACKTEST?
----------------------
Optimizing parameters over a whole history and reporting the result of the
winning combination is not a test — it is a description of the past. With
enough parameters you can erase every historical losing trade and learn
nothing generalizable. The gap between in-sample and out-of-sample
performance IS the overfitting measurement, and you only get it by never
letting the optimizer see the data it will be judged on.

Walk-forward: optimize on a rolling training window, evaluate on the
untouched window immediately after it, roll forward, repeat. The stitched
out-of-sample results are the only equity curve worth believing.

SCOPE — DELIBERATELY DETERMINISTIC STRATEGIES ONLY
--------------------------------------------------
This runs a full backtest per (parameter combination x window). A modest
6-combination grid over 8 windows is ~54 backtests. That is trivial for a
deterministic strategy and financially absurd for the LLM agent pipeline,
which spends a full multi-agent cycle per decision — the same sweep would
cost thousands of dollars and still be invalid, because an LLM's training
data already covers the historical window it is being "tested" on
(lookahead through pretraining).

So: walk-forward the deterministic layer (signal rules, stops, sizing).
Validate the LLM layer forward, in paper trading, on data that did not
exist when the model was trained. Those are different instruments for
different questions; conflating them is how people end up trusting a
backtest that could never have been valid.
"""

import itertools
import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    """One train/test fold."""
    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: Dict[str, Any] = field(default_factory=dict)
    in_sample_sharpe: float = 0.0
    in_sample_return_pct: float = 0.0
    out_of_sample_sharpe: float = 0.0
    out_of_sample_return_pct: float = 0.0
    out_of_sample_trades: int = 0


@dataclass
class WalkForwardResult:
    ticker: str
    windows: List[WalkForwardWindow] = field(default_factory=list)
    param_grid_size: int = 0
    total_backtests: int = 0

    @property
    def mean_in_sample_sharpe(self) -> float:
        vals = [w.in_sample_sharpe for w in self.windows]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def mean_out_of_sample_sharpe(self) -> float:
        vals = [w.out_of_sample_sharpe for w in self.windows]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def degradation(self) -> float:
        """In-sample Sharpe minus out-of-sample Sharpe.

        This number is the point of the whole exercise. Near zero means the
        parameters describe something real. Large and positive means the
        optimizer memorized noise — and the in-sample figure you would
        otherwise have reported was fiction.
        """
        return self.mean_in_sample_sharpe - self.mean_out_of_sample_sharpe

    @property
    def param_stability(self) -> float:
        """Fraction of windows that selected the single most common parameter set.

        A strategy whose "optimal" parameters change every window does not
        have optimal parameters; it has a curve-fitting procedure.
        """
        if not self.windows:
            return 0.0
        keys = [tuple(sorted(w.best_params.items())) for w in self.windows]
        most_common = max(set(keys), key=keys.count)
        return keys.count(most_common) / len(keys)


def walk_forward_analysis(
    ticker: str,
    start_date: str,
    end_date: str,
    strategy_factory: Callable[..., Callable],
    param_grid: Dict[str, Sequence[Any]],
    train_bars: int = 120,
    test_bars: int = 60,
    config: Optional[Dict[str, Any]] = None,
    min_trades_in_sample: int = 5,
) -> WalkForwardResult:
    """Run rolling-window optimization with out-of-sample evaluation.

    Args:
        ticker: Symbol to test.
        start_date / end_date: Full history to slice into folds.
        strategy_factory: Callable that takes the parameters as keyword
            arguments and returns a `decision_fn` for BacktestRunner —
            e.g. `make_sma_crossover_decision` from baselines.py.
        param_grid: {param_name: [values]}, expanded to a full cartesian product.
        train_bars: Bars per optimization window.
        test_bars: Bars per out-of-sample window (also the roll step, so
            test windows tile the history without overlapping).
        config: TradingAgents config (supplies the cost model).
        min_trades_in_sample: Parameter sets producing fewer in-sample
            trades than this are skipped — a 2-trade Sharpe is noise, and
            without this guard the optimizer reliably "wins" by selecting
            whichever combination barely traded at all.

    Returns:
        WalkForwardResult — read `.degradation` and `.param_stability` first.
    """
    from .backtest_runner import BacktestRunner, _fetch_bars

    result = WalkForwardResult(ticker=ticker)

    # Fetch once; every fold is a slice of this same series.
    bars = _fetch_bars(ticker, start_date, end_date)
    if len(bars) < train_bars + test_bars:
        logger.error(
            "Not enough bars for walk-forward on %s: have %d, need %d",
            ticker, len(bars), train_bars + test_bars,
        )
        return result

    names = list(param_grid.keys())
    combos = [dict(zip(names, values)) for values in itertools.product(*param_grid.values())]
    result.param_grid_size = len(combos)

    def _run(decision_fn, lo: int, hi: int):
        runner = BacktestRunner(config=config, decision_fn=decision_fn)
        return runner.run(ticker, bars[lo].date, bars[hi].date, bars=bars)

    window_idx = 0
    cursor = 0
    while cursor + train_bars + test_bars <= len(bars):
        train_lo, train_hi = cursor, cursor + train_bars - 1
        test_lo, test_hi = cursor + train_bars, cursor + train_bars + test_bars - 1

        window = WalkForwardWindow(
            index=window_idx,
            train_start=bars[train_lo].date, train_end=bars[train_hi].date,
            test_start=bars[test_lo].date, test_end=bars[test_hi].date,
        )

        # ── Optimize on the training window ──
        best_combo, best_metrics = None, None
        for combo in combos:
            metrics = _run(strategy_factory(**combo), train_lo, train_hi)
            result.total_backtests += 1
            traded = metrics.buy_count + metrics.sell_count
            if traded < min_trades_in_sample:
                continue
            if best_metrics is None or metrics.sharpe_ratio > best_metrics.sharpe_ratio:
                best_combo, best_metrics = combo, metrics

        if best_combo is None:
            logger.warning(
                "Window %d: no parameter set reached %d in-sample trades — skipped.",
                window_idx, min_trades_in_sample,
            )
            cursor += test_bars
            window_idx += 1
            continue

        window.best_params = best_combo
        window.in_sample_sharpe = best_metrics.sharpe_ratio
        window.in_sample_return_pct = best_metrics.total_return_pct

        # ── Evaluate on the untouched window ──
        oos = _run(strategy_factory(**best_combo), test_lo, test_hi)
        result.total_backtests += 1
        window.out_of_sample_sharpe = oos.sharpe_ratio
        window.out_of_sample_return_pct = oos.total_return_pct
        window.out_of_sample_trades = oos.buy_count + oos.sell_count

        logger.info(
            "Window %d: params=%s IS_Sharpe=%.2f OOS_Sharpe=%.2f",
            window_idx, best_combo, window.in_sample_sharpe, window.out_of_sample_sharpe,
        )

        result.windows.append(window)
        cursor += test_bars
        window_idx += 1

    return result


def format_walk_forward_report(result: WalkForwardResult) -> str:
    """Render a walk-forward result as markdown."""
    lines = [
        f"# Walk-Forward Analysis — {result.ticker}",
        "",
        f"**Parameter combinations**: {result.param_grid_size}  ",
        f"**Windows**: {len(result.windows)}  ",
        f"**Backtests run**: {result.total_backtests}",
        "",
    ]

    if not result.windows:
        lines.append("No valid windows — widen the date range or lower `min_trades_in_sample`.")
        return "\n".join(lines)

    lines += [
        "| # | Train | Test | Best Params | IS Sharpe | OOS Sharpe | OOS Return | OOS Trades |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for w in result.windows:
        params = ", ".join(f"{k}={v}" for k, v in w.best_params.items())
        lines.append(
            f"| {w.index} | {w.train_start}→{w.train_end} | {w.test_start}→{w.test_end} "
            f"| {params} | {w.in_sample_sharpe:.2f} | {w.out_of_sample_sharpe:.2f} "
            f"| {w.out_of_sample_return_pct:+.2f}% | {w.out_of_sample_trades} |"
        )

    oos_sharpes = [w.out_of_sample_sharpe for w in result.windows]
    positive = sum(1 for s in oos_sharpes if s > 0)

    lines += [
        "",
        "## Verdict",
        "",
        f"- Mean in-sample Sharpe: **{result.mean_in_sample_sharpe:.2f}**",
        f"- Mean out-of-sample Sharpe: **{result.mean_out_of_sample_sharpe:.2f}**",
        f"- **Degradation (IS − OOS): {result.degradation:+.2f}**",
        f"- Windows with positive OOS Sharpe: {positive}/{len(oos_sharpes)}",
        f"- Parameter stability: {result.param_stability:.0%} of windows chose the same set",
        "",
    ]

    if result.degradation > 1.0:
        lines.append(
            "> **Severe overfitting.** In-sample results are largely curve-fit; the "
            "out-of-sample number is the one that would have happened. Reduce the "
            "parameter count before doing anything else."
        )
    elif result.degradation > 0.5:
        lines.append(
            "> **Moderate overfitting.** Some in-sample edge does not survive. Treat "
            "the OOS figure as the honest estimate and expect live to be no better."
        )
    else:
        lines.append(
            "> Degradation is small — parameters appear to describe something "
            "persistent rather than window-specific noise."
        )

    if result.param_stability < 0.5:
        lines.append(
            "> **Unstable parameters**: the optimizer picks a different 'best' setting in "
            "most windows. That is a curve-fitting procedure, not a parameter — prefer a "
            "single fixed value chosen for a structural reason over re-optimizing."
        )

    if result.mean_out_of_sample_sharpe <= 0:
        lines.append(
            "> **Out-of-sample Sharpe is not positive.** This strategy has no demonstrated "
            "edge. Do not allocate capital to it, and do not let Kelly size it."
        )

    return "\n".join(lines)
