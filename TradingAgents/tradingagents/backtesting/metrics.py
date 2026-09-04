"""Backtest metrics calculator.

Computes directional accuracy, Sharpe ratio, win rate, max drawdown,
and profit factor from a sequence of backtest trade results.

Each TradeResult represents a REAL simulated round-trip: entry, then an
exit that actually respects the stop-loss / take-profit / holding period
the Trader agent specified — not a fixed 1-day mark-to-market. See
backtest_runner.py's _simulate_exit() for the exit logic.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional

# Trading days per calendar year — used to annualize Sharpe.
TRADING_DAYS_PER_YEAR = 252


@dataclass
class TradeResult:
    """A single simulated round-trip trade from a backtest."""
    date: str                  # entry date
    ticker: str
    decision: str              # BUY / SELL / HOLD (STRONG_* normalized by caller)
    confidence: float          # 0.0 - 1.0
    entry_price: float
    exit_price: float
    exit_date: str = ""
    # Why the position closed — the single most useful field for judging
    # whether a strategy's edge is real or an artifact of the exit rule.
    exit_reason: str = "time_exit"   # stop_loss | take_profit | time_exit | data_end
    holding_days: int = 1
    quantity_pct: float = 1.0        # fraction of equity allocated (0.0-1.0)
    cost_pct: float = 0.0            # round-trip commission+slippage, % of notional

    # ── Computed ──
    price_return_pct: float = 0.0      # raw asset move, direction-agnostic
    strategy_return_pct: float = 0.0   # direction-signed, position-sized, net of costs
    direction_correct: Optional[bool] = None

    def __post_init__(self):
        if self.entry_price > 0:
            self.price_return_pct = (
                (self.exit_price - self.entry_price) / self.entry_price
            ) * 100.0

        if self.decision in ("BUY", "STRONG_BUY"):
            gross_pct = self.price_return_pct
            self.direction_correct = self.exit_price > self.entry_price
        elif self.decision in ("SELL", "STRONG_SELL"):
            gross_pct = -self.price_return_pct   # short profits when price falls
            self.direction_correct = self.exit_price < self.entry_price
        else:
            gross_pct = 0.0
            self.direction_correct = None        # HOLD is neutral, not scored

        # Costs are a % of notional, so they're deducted BEFORE scaling by
        # allocation — a 10%-of-equity position pays 10% of the round-trip cost.
        self.strategy_return_pct = (gross_pct - self.cost_pct) * self.quantity_pct


@dataclass
class BacktestMetrics:
    """Aggregated backtest performance metrics."""

    # Counts
    total_days: int = 0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0

    # Directional accuracy
    correct_calls: int = 0
    incorrect_calls: int = 0
    directional_accuracy: float = 0.0

    # PnL metrics (all position-sized and net of costs)
    total_return_pct: float = 0.0
    avg_return_per_trade_pct: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0

    # Risk metrics
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Exit-rule breakdown — tells you whether the edge comes from the
    # signal or from the stop/target placement.
    stop_loss_exits: int = 0
    take_profit_exits: int = 0
    time_exits: int = 0
    avg_holding_days: float = 0.0

    # Confidence calibration
    avg_confidence: float = 0.0
    avg_confidence_correct: float = 0.0
    avg_confidence_incorrect: float = 0.0

    # Per-trade results
    trades: List[TradeResult] = field(default_factory=list)


def calculate_metrics(
    trades: List[TradeResult],
    risk_free_rate_annual: float = 0.05,
) -> BacktestMetrics:
    """Calculate comprehensive backtest metrics from trade results.

    Args:
        trades: List of TradeResult from a backtest run. Assumed
            non-overlapping and chronological (BacktestRunner enforces
            this by default) — overlapping trades would make the
            compounded equity curve and Sharpe meaningless, since the
            same capital can't fund two positions at once.
        risk_free_rate_annual: Annualized risk-free rate, as a decimal
            fraction (0.05 = 5%/yr).

    Returns:
        BacktestMetrics with all computed fields
    """
    m = BacktestMetrics(trades=trades, total_days=len(trades))

    if not trades:
        return m

    # --- Counts ---
    m.buy_count = sum(1 for t in trades if t.decision in ("BUY", "STRONG_BUY"))
    m.sell_count = sum(1 for t in trades if t.decision in ("SELL", "STRONG_SELL"))
    m.hold_count = sum(1 for t in trades if t.decision == "HOLD")

    # --- Directional Accuracy ---
    actionable = [t for t in trades if t.direction_correct is not None]
    m.correct_calls = sum(1 for t in actionable if t.direction_correct)
    m.incorrect_calls = sum(1 for t in actionable if not t.direction_correct)

    if actionable:
        m.directional_accuracy = m.correct_calls / len(actionable) * 100.0

    # --- Exit-rule breakdown ---
    m.stop_loss_exits = sum(1 for t in actionable if t.exit_reason == "stop_loss")
    m.take_profit_exits = sum(1 for t in actionable if t.exit_reason == "take_profit")
    m.time_exits = sum(1 for t in actionable if t.exit_reason in ("time_exit", "data_end"))
    if actionable:
        m.avg_holding_days = sum(t.holding_days for t in actionable) / len(actionable)

    # --- PnL (only actionable trades; HOLD contributes nothing) ---
    pnl_trades = [t.strategy_return_pct for t in actionable]

    if pnl_trades:
        m.avg_return_per_trade_pct = sum(pnl_trades) / len(pnl_trades)
        m.best_trade_pct = max(pnl_trades)
        m.worst_trade_pct = min(pnl_trades)

        wins = [p for p in pnl_trades if p > 0]
        losses = [p for p in pnl_trades if p < 0]
        m.win_rate = len(wins) / len(pnl_trades) * 100.0

        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        m.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # --- Equity curve: compounded, so total return and max drawdown
        # are derived from the SAME series (these used to disagree —
        # total_return was a plain sum while drawdown compounded). ---
        equity = 100.0
        peak = equity
        max_dd = 0.0
        for pnl in pnl_trades:
            equity *= 1 + pnl / 100.0
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)
        m.total_return_pct = equity - 100.0
        m.max_drawdown_pct = max_dd

        # --- Sharpe ---
        # Annualization uses the ACTUAL average holding period, not an
        # assumed 1 day: a strategy holding 20 days has ~12.6 periods/yr,
        # not 252, and using sqrt(252) there would overstate Sharpe by
        # ~4.5x. The risk-free rate is also converted to percent units to
        # match pnl_trades (previously a decimal fraction was subtracted
        # from percent values, making the adjustment ~100x too small).
        if len(pnl_trades) >= 2:
            holding = max(m.avg_holding_days, 1.0)
            periods_per_year = TRADING_DAYS_PER_YEAR / holding
            rf_per_period_pct = (risk_free_rate_annual * 100.0) / periods_per_year

            excess = [r - rf_per_period_pct for r in pnl_trades]
            mean_excess = sum(excess) / len(excess)
            variance = sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0
            m.sharpe_ratio = (
                (mean_excess / std_dev) * math.sqrt(periods_per_year)
                if std_dev > 0 else 0.0
            )

    # --- Confidence Calibration ---
    all_conf = [t.confidence for t in trades if t.confidence > 0]
    correct_conf = [t.confidence for t in actionable if t.direction_correct and t.confidence > 0]
    incorrect_conf = [t.confidence for t in actionable if not t.direction_correct and t.confidence > 0]

    m.avg_confidence = sum(all_conf) / len(all_conf) if all_conf else 0.0
    m.avg_confidence_correct = sum(correct_conf) / len(correct_conf) if correct_conf else 0.0
    m.avg_confidence_incorrect = sum(incorrect_conf) / len(incorrect_conf) if incorrect_conf else 0.0

    return m
