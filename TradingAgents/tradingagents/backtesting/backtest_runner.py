"""Backtest runner for TradingAgents.

Runs a decision source over historical dates and simulates each resulting
trade REALISTICALLY — respecting the stop-loss, take-profit and holding
period the decision actually specified, charging round-trip costs, and
sizing by the requested allocation.

This previously compared every decision against a fixed next-day close,
ignoring stop_loss_pct / take_profit_pct / time_horizon / quantity_pct
entirely. That measured a strategy nobody runs: a 1-day, unstopped,
full-size hold. Numbers from it could not be used to judge the live
system, which exits on stops and targets.

The decision source is pluggable (`decision_fn`) so the same simulation
engine drives both the LLM agent pipeline and cheap deterministic
baselines — see baselines.py. Comparing an expensive agent stack against
buy-and-hold on an IDENTICAL simulator is the only way to know whether
the agents add value.

Usage:
    # Full agent pipeline (expensive — one LLM cycle per entry)
    runner = BacktestRunner(config=my_config)
    metrics = runner.run("NVDA", "2026-01-05", "2026-03-28")
    print(runner.get_report())

    # Deterministic baseline (free, instant)
    from tradingagents.backtesting.baselines import sma_crossover_decision
    runner = BacktestRunner(decision_fn=sma_crossover_decision)
    metrics = runner.run("NVDA", "2026-01-05", "2026-03-28")
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import yfinance as yf

from .metrics import TradeResult, BacktestMetrics, calculate_metrics
from .report import generate_report as _generate_report

logger = logging.getLogger(__name__)

# time_horizon (from TradeDecision) -> max bars to hold before a time exit.
_HOLDING_DAYS = {
    "intraday": 1,
    "short_term": 5,
    "medium_term": 20,
    "long_term": 60,
}
_DEFAULT_HOLDING_DAYS = 5

_LONG_ACTIONS = ("BUY", "STRONG_BUY")
_SHORT_ACTIONS = ("SELL", "STRONG_SELL")


@dataclass
class Bar:
    """One OHLC bar."""
    date: str
    open: float
    high: float
    low: float
    close: float


def _fetch_bars(ticker: str, start_date: str, end_date: str, lookahead_days: int = 90) -> List[Bar]:
    """Fetch the full OHLC series once, with a tail buffer so trades opened
    near `end_date` still have bars to exit on.

    This replaces the old per-date `_get_price_on_date()`, which hit
    yfinance twice for every single trading day (~500 network calls for a
    one-year backtest) — slow, rate-limit-prone, and a silent source of
    skipped days whenever a request failed.
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=lookahead_days)
    data = yf.Ticker(ticker).history(start=start_date, end=end_dt.strftime("%Y-%m-%d"))
    if data.empty:
        return []
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    bars: List[Bar] = []
    for idx, row in data.iterrows():
        bars.append(Bar(
            date=idx.strftime("%Y-%m-%d"),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
        ))
    return bars


def _extract_decision(signal: Any) -> Dict[str, Any]:
    """Pull the full trade specification out of a decision payload.

    Accepts the JSON string a TradeDecision serializes to, an already-parsed
    dict, or a bare "BUY"/"SELL"/"HOLD" fallback string.

    NOTE: reads `confidence_score` (the real TradeDecision field name).
    The old code read `confidence`, which does not exist on the model — so
    confidence silently defaulted to 0.5 on EVERY trade, making all the
    confidence-calibration metrics in the report meaningless.
    """
    out = {
        "action": "HOLD",
        "confidence": 0.5,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "quantity_pct": 1.0,
        "time_horizon": None,
    }
    if not signal:
        return out

    data: Optional[dict] = None
    if isinstance(signal, dict):
        data = signal
    elif isinstance(signal, str):
        try:
            parsed = json.loads(signal)
            if isinstance(parsed, dict):
                data = parsed
        except (json.JSONDecodeError, TypeError):
            # Try a JSON object embedded in surrounding prose. Uses a
            # greedy match so nested objects/arrays survive — the old
            # `\{[^{}]+\}` pattern failed on any nested structure.
            match = re.search(r"\{.*\}", signal, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, dict):
                        data = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

    if data is not None:
        action = str(data.get("action", "HOLD")).upper()
        out["action"] = action
        conf = data.get("confidence_score", data.get("confidence"))
        if conf is not None:
            try:
                out["confidence"] = float(conf)
            except (TypeError, ValueError):
                pass
        for key in ("stop_loss_pct", "take_profit_pct"):
            val = data.get(key)
            if val is not None:
                try:
                    out[key] = float(val)
                except (TypeError, ValueError):
                    pass
        qty = data.get("quantity_pct")
        if qty is not None:
            try:
                out["quantity_pct"] = max(0.0, min(1.0, float(qty)))
            except (TypeError, ValueError):
                pass
        out["time_horizon"] = data.get("time_horizon")
        return out

    # Bare-text fallback
    text = str(signal).upper()
    if "STRONG_BUY" in text or "STRONG BUY" in text:
        out["action"] = "STRONG_BUY"
    elif "STRONG_SELL" in text or "STRONG SELL" in text:
        out["action"] = "STRONG_SELL"
    elif "BUY" in text:
        out["action"] = "BUY"
    elif "SELL" in text:
        out["action"] = "SELL"
    return out


def _simulate_exit(
    bars: List[Bar],
    entry_idx: int,
    entry_price: float,
    is_long: bool,
    stop_pct: Optional[float],
    target_pct: Optional[float],
    max_holding_days: int,
) -> Optional[tuple]:
    """Walk forward bar-by-bar and resolve how the position actually closed.

    Returns (exit_price, exit_idx, exit_reason) or None if there is no bar
    after entry to exit on.

    Two deliberate conservative choices, because a daily bar hides the
    intrabar path:
      1. Stops are checked BEFORE targets. If a bar's range spans both, we
         assume the stop hit first — the pessimistic branch. Assuming the
         target instead would manufacture free profit on exactly the most
         volatile (and most consequential) bars.
      2. A stop that GAPS through fills at the open, not at the stop price
         (`min(stop, open)` for longs) — real stops don't hold across gaps.
         Targets get no symmetric gap bonus, so the bias stays one-sided
         against the strategy rather than for it.
    """
    if entry_idx + 1 >= len(bars):
        return None

    if is_long:
        stop_price = entry_price * (1 - stop_pct) if stop_pct else None
        target_price = entry_price * (1 + target_pct) if target_pct else None
    else:
        stop_price = entry_price * (1 + stop_pct) if stop_pct else None
        target_price = entry_price * (1 - target_pct) if target_pct else None

    horizon_idx = entry_idx + max_holding_days
    last_idx = min(horizon_idx, len(bars) - 1)

    for i in range(entry_idx + 1, last_idx + 1):
        bar = bars[i]
        if is_long:
            if stop_price is not None and bar.low <= stop_price:
                return min(stop_price, bar.open), i, "stop_loss"
            if target_price is not None and bar.high >= target_price:
                return target_price, i, "take_profit"
        else:
            if stop_price is not None and bar.high >= stop_price:
                return max(stop_price, bar.open), i, "stop_loss"
            if target_price is not None and bar.low <= target_price:
                return target_price, i, "take_profit"

    reason = "time_exit" if last_idx >= horizon_idx else "data_end"
    return bars[last_idx].close, last_idx, reason


class BacktestRunner:
    """Runs a decision source over historical dates with realistic exits.

    For each eligible trading day:
    1. Asks the decision source (LLM agent graph, or an injected
       `decision_fn`) for a decision
    2. Enters at that day's close
    3. Simulates the exit against real OHLC bars — stop-loss, take-profit,
       or holding-period expiry, whichever comes first
    4. Charges round-trip costs and scales by the requested allocation
    5. Computes aggregate performance metrics

    By default positions do NOT overlap: while a trade is open, later
    signals are skipped. This mirrors the live system (which has
    max_concurrent_positions and a per-ticker cooldown), and it keeps the
    compounded equity curve honest — overlapping trades would double-count
    the same capital and produce autocorrelated returns that inflate Sharpe.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        selected_analysts: Optional[List[str]] = None,
        decision_fn: Optional[Callable[..., Any]] = None,
        allow_overlapping: bool = False,
    ):
        """Initialize the backtest runner.

        Args:
            config: TradingAgents config dict. If None, uses DEFAULT_CONFIG.
            selected_analysts: Analyst types for the LLM graph.
            decision_fn: Optional callable
                `(ticker, bars, idx) -> decision payload`, used INSTEAD of
                the LLM pipeline. Lets deterministic baselines (see
                baselines.py) and cheap walk-forward runs reuse this exact
                simulator, without spending an LLM cycle per bar.
            allow_overlapping: Permit a new entry while one is still open.
                Off by default — see the class docstring.
        """
        self.config = config
        self.selected_analysts = selected_analysts or [
            "market", "social", "news", "fundamentals",
        ]
        self.decision_fn = decision_fn
        self.allow_overlapping = allow_overlapping
        self._graph = None
        self._metrics: Optional[BacktestMetrics] = None
        self._ticker: str = ""
        self._start_date: str = ""
        self._end_date: str = ""

    def _round_trip_cost_pct(self) -> float:
        """Round-trip commission + slippage as a percentage of notional.

        Pulled from the SAME execution config the live paper broker uses,
        so a backtest can't quietly assume cheaper fills than production.
        """
        exec_cfg = (self.config or {}).get("execution", {})
        commission = float(exec_cfg.get("commission_pct", 0.001))
        slippage = float(exec_cfg.get("slippage_pct", 0.0005))
        return (commission + slippage) * 2 * 100.0  # entry + exit, in percent

    def _ensure_graph(self):
        """Lazily initialize the TradingAgentsGraph (expensive)."""
        if self._graph is not None:
            return

        from tradingagents.graph.trading_graph import TradingAgentsGraph

        # Force execution to disabled for backtesting (no real trades)
        bt_config = dict(self.config) if self.config else {}
        if "execution" not in bt_config:
            bt_config["execution"] = {}
        bt_config["execution"]["mode"] = "disabled"

        self._graph = TradingAgentsGraph(
            selected_analysts=self.selected_analysts,
            debug=False,
            config=bt_config,
        )

    def _get_decision(self, ticker: str, bars: List[Bar], idx: int) -> Any:
        """Ask the active decision source for a decision on bars[idx]."""
        if self.decision_fn is not None:
            return self.decision_fn(ticker, bars, idx)

        self._ensure_graph()
        _final_state, decision_json, _order_result = self._graph.propagate(
            ticker, bars[idx].date, auto_execute=False
        )
        return decision_json

    def run(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        skip_dates: Optional[List[str]] = None,
        bars: Optional[List[Bar]] = None,
    ) -> BacktestMetrics:
        """Run the backtest on a date range.

        Args:
            ticker: Ticker symbol to backtest (e.g., "NVDA", "BTC-USD")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            skip_dates: Optional list of dates to skip
            bars: Pre-fetched OHLC series to reuse instead of downloading.
                Walk-forward analysis re-runs the same instrument dozens of
                times over sliding windows; without this it would refetch
                the identical series on every one. Bars outside
                [start_date, end_date] are still honored for exits, exactly
                as the fetched tail buffer is.

        Returns:
            BacktestMetrics with comprehensive performance data
        """
        self._ticker = ticker
        self._start_date = start_date
        self._end_date = end_date

        logger.info("Starting backtest for %s from %s to %s", ticker, start_date, end_date)

        if bars is None:
            bars = _fetch_bars(ticker, start_date, end_date)
        if not bars:
            logger.error("No price data for %s in range %s to %s", ticker, start_date, end_date)
            return BacktestMetrics()

        # Entries are confined to the requested window; bars outside it
        # exist only so positions opened inside it can still exit.
        entry_indices = [
            i for i, b in enumerate(bars) if start_date <= b.date <= end_date
        ]
        if not entry_indices:
            logger.warning("No bars inside %s..%s for %s", start_date, end_date, ticker)
            return BacktestMetrics()
        first_entry_idx = entry_indices[0]
        entry_limit = entry_indices[-1] + 1
        logger.info(
            "%d bars for %s (%d eligible for entry)",
            len(bars), ticker, entry_limit - first_entry_idx,
        )

        skip_set = set(skip_dates or [])
        cost_pct = self._round_trip_cost_pct()
        trade_results: List[TradeResult] = []
        blocked_until_idx = -1   # non-overlap guard

        for idx in range(first_entry_idx, entry_limit):
            bar = bars[idx]
            if bar.date in skip_set:
                continue
            if not self.allow_overlapping and idx <= blocked_until_idx:
                continue

            logger.info(
                "[%d/%d] Deciding for %s on %s...",
                idx - first_entry_idx + 1, entry_limit - first_entry_idx, ticker, bar.date,
            )

            try:
                spec = _extract_decision(self._get_decision(ticker, bars, idx))
                action = spec["action"]

                if action not in _LONG_ACTIONS and action not in _SHORT_ACTIONS:
                    # HOLD — record it (for decision-mix stats) but open nothing.
                    trade_results.append(TradeResult(
                        date=bar.date, ticker=ticker, decision="HOLD",
                        confidence=spec["confidence"],
                        entry_price=bar.close, exit_price=bar.close,
                        exit_date=bar.date, exit_reason="time_exit",
                        holding_days=0, quantity_pct=0.0, cost_pct=0.0,
                    ))
                    continue

                is_long = action in _LONG_ACTIONS
                max_hold = _HOLDING_DAYS.get(spec["time_horizon"] or "", _DEFAULT_HOLDING_DAYS)

                exit_info = _simulate_exit(
                    bars=bars,
                    entry_idx=idx,
                    entry_price=bar.close,
                    is_long=is_long,
                    stop_pct=spec["stop_loss_pct"],
                    target_pct=spec["take_profit_pct"],
                    max_holding_days=max_hold,
                )
                if exit_info is None:
                    logger.warning("No bars after %s to exit on, stopping.", bar.date)
                    break

                exit_price, exit_idx, exit_reason = exit_info

                result = TradeResult(
                    date=bar.date,
                    ticker=ticker,
                    decision=action,
                    confidence=spec["confidence"],
                    entry_price=bar.close,
                    exit_price=exit_price,
                    exit_date=bars[exit_idx].date,
                    exit_reason=exit_reason,
                    holding_days=exit_idx - idx,
                    quantity_pct=spec["quantity_pct"],
                    cost_pct=cost_pct,
                )
                trade_results.append(result)
                blocked_until_idx = exit_idx

                logger.info(
                    "  -> %s (conf=%.2f, size=%.0f%%) held %dd, exit=%s, net=%+.2f%%",
                    action, result.confidence, result.quantity_pct * 100,
                    result.holding_days, exit_reason, result.strategy_return_pct,
                )

            except Exception as e:
                logger.error("Error on %s: %s", bar.date, e, exc_info=True)
                continue

        risk_free = 0.05
        if self.config:
            risk_free = self.config.get("storage", {}).get("risk_free_rate_annual", 0.05)

        self._metrics = calculate_metrics(trade_results, risk_free_rate_annual=risk_free)

        logger.info(
            "Backtest complete: %d decisions, Accuracy=%.1f%%, Sharpe=%.2f, "
            "WinRate=%.1f%%, Return=%+.2f%%, MaxDD=%.2f%%",
            self._metrics.total_days,
            self._metrics.directional_accuracy,
            self._metrics.sharpe_ratio,
            self._metrics.win_rate,
            self._metrics.total_return_pct,
            self._metrics.max_drawdown_pct,
        )

        return self._metrics

    def get_report(self, output_dir: Optional[str] = None) -> str:
        """Generate markdown report from last backtest run.

        Args:
            output_dir: If specified, save report to this directory

        Returns:
            Markdown report string
        """
        if self._metrics is None:
            return "No backtest has been run yet. Call .run() first."

        return _generate_report(
            metrics=self._metrics,
            ticker=self._ticker,
            start_date=self._start_date,
            end_date=self._end_date,
            output_dir=output_dir,
        )
