"""Backtest runner for TradingAgents.

Runs the full agent pipeline on historical dates and compares
decisions against actual next-day price movements.

Usage:
    runner = BacktestRunner(config=my_config)
    metrics = runner.run("NVDA", "2026-01-05", "2026-03-28")
    print(runner.generate_report())
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import yfinance as yf

from .metrics import TradeResult, BacktestMetrics, calculate_metrics
from .report import generate_report as _generate_report

logger = logging.getLogger(__name__)


def _get_trading_days(ticker: str, start_date: str, end_date: str) -> List[str]:
    """Get actual trading days from yfinance historical data.

    Returns list of date strings (YYYY-MM-DD) where the market was open.
    """
    data = yf.Ticker(ticker).history(start=start_date, end=end_date)
    if data.empty:
        return []
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return [d.strftime("%Y-%m-%d") for d in data.index]


def _get_price_on_date(ticker: str, date_str: str) -> Optional[float]:
    """Get closing price for a ticker on a specific date.

    Looks at a 5-day window to handle weekends/holidays.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = dt - timedelta(days=1)
    end = dt + timedelta(days=5)
    data = yf.Ticker(ticker).history(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
    )
    if data.empty:
        return None
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    # Find the exact date or nearest after
    for idx_date in data.index:
        if idx_date.strftime("%Y-%m-%d") >= date_str:
            return float(data.loc[idx_date, "Close"])
    # Fallback: last available
    return float(data["Close"].iloc[-1])


def _extract_decision_from_signal(signal_json: str) -> tuple:
    """Extract (action, confidence) from a processed signal string.

    The signal may be:
    - A JSON string with 'action' and 'confidence' fields
    - A simple text like "BUY" / "SELL" / "HOLD"

    Returns:
        Tuple of (action: str, confidence: float)
    """
    action = "HOLD"
    confidence = 0.5

    if not signal_json:
        return action, confidence

    # Try JSON parse first
    try:
        data = json.loads(signal_json)
        action = data.get("action", "HOLD").upper()
        confidence = float(data.get("confidence", 0.5))
        return action, confidence
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find JSON embedded in text
    json_match = re.search(r'\{[^{}]+\}', signal_json)
    if json_match:
        try:
            data = json.loads(json_match.group())
            action = data.get("action", "HOLD").upper()
            confidence = float(data.get("confidence", 0.5))
            return action, confidence
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: simple text extraction
    text = signal_json.upper()
    if "BUY" in text:
        action = "BUY"
    elif "SELL" in text:
        action = "SELL"
    else:
        action = "HOLD"

    return action, confidence


class BacktestRunner:
    """Runs the TradingAgents pipeline on historical dates.

    For each trading day in the specified range:
    1. Runs the full agent graph (analysts -> synthesizer -> debate -> risk)
    2. Extracts the BUY/SELL/HOLD decision
    3. Compares against actual next-day price movement
    4. Computes aggregate performance metrics

    Example:
        runner = BacktestRunner(config=config)
        metrics = runner.run("NVDA", "2026-01-05", "2026-03-28")
        report = runner.generate_report()
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        selected_analysts: Optional[List[str]] = None,
    ):
        """Initialize the backtest runner.

        Args:
            config: TradingAgents config dict. If None, uses DEFAULT_CONFIG.
            selected_analysts: List of analyst types to use. If None, uses defaults.
        """
        self.config = config
        self.selected_analysts = selected_analysts or [
            "market", "social", "news", "fundamentals",
        ]
        self._graph = None
        self._metrics: Optional[BacktestMetrics] = None
        self._ticker: str = ""
        self._start_date: str = ""
        self._end_date: str = ""

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

    def run(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        skip_dates: Optional[List[str]] = None,
    ) -> BacktestMetrics:
        """Run the backtest on a date range.

        Args:
            ticker: Ticker symbol to backtest (e.g., "NVDA", "BTC-USD")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            skip_dates: Optional list of dates to skip

        Returns:
            BacktestMetrics with comprehensive performance data
        """
        self._ticker = ticker
        self._start_date = start_date
        self._end_date = end_date

        logger.info("Starting backtest for %s from %s to %s", ticker, start_date, end_date)

        # Get actual trading days
        trading_days = _get_trading_days(ticker, start_date, end_date)
        if not trading_days:
            logger.error("No trading days found for %s in range %s to %s", ticker, start_date, end_date)
            return BacktestMetrics()

        logger.info("Found %d trading days for %s", len(trading_days), ticker)

        skip_set = set(skip_dates or [])

        # Initialize graph
        self._ensure_graph()

        # Run pipeline for each trading day
        trade_results: List[TradeResult] = []

        for i, trade_date in enumerate(trading_days[:-1]):  # skip last day (no next-day data)
            if trade_date in skip_set:
                logger.info("Skipping %s (in skip list)", trade_date)
                continue

            next_date = trading_days[i + 1]

            logger.info(
                "[%d/%d] Running analysis for %s on %s...",
                i + 1, len(trading_days) - 1, ticker, trade_date,
            )

            try:
                # Run full agent pipeline
                _final_state, decision_json, _order_result = self._graph.propagate(
                    ticker, trade_date, auto_execute=False
                )

                # Extract decision
                action, confidence = _extract_decision_from_signal(decision_json)

                # Get prices
                entry_price = _get_price_on_date(ticker, trade_date)
                next_day_price = _get_price_on_date(ticker, next_date)

                if entry_price is None or next_day_price is None:
                    logger.warning("Price data missing for %s or %s, skipping", trade_date, next_date)
                    continue

                result = TradeResult(
                    date=trade_date,
                    ticker=ticker,
                    decision=action,
                    confidence=confidence,
                    entry_price=entry_price,
                    next_day_price=next_day_price,
                )

                trade_results.append(result)

                correct_str = "CORRECT" if result.direction_correct else (
                    "INCORRECT" if result.direction_correct is False else "N/A"
                )
                logger.info(
                    "  -> Decision: %s (conf=%.2f), Return: %+.2f%%, %s",
                    action, confidence, result.actual_return_pct, correct_str,
                )

            except Exception as e:
                logger.error("Error on %s: %s", trade_date, e, exc_info=True)
                continue

        # Calculate metrics
        risk_free = 0.05
        if self.config:
            risk_free = self.config.get("storage", {}).get("risk_free_rate_annual", 0.05)

        self._metrics = calculate_metrics(trade_results, risk_free_rate_annual=risk_free)

        logger.info(
            "Backtest complete: %d days, Accuracy=%.1f%%, Sharpe=%.2f, WinRate=%.1f%%",
            self._metrics.total_days,
            self._metrics.directional_accuracy,
            self._metrics.sharpe_ratio,
            self._metrics.win_rate,
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
