"""Backtest metrics calculator.

Computes directional accuracy, Sharpe ratio, win rate, max drawdown,
and profit factor from a sequence of backtest trade results.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TradeResult:
    """Single trade result from a backtest day."""
    date: str
    ticker: str
    decision: str          # BUY / SELL / HOLD
    confidence: float      # 0.0 - 1.0
    entry_price: float     # price on decision day
    next_day_price: float  # price on next trading day
    actual_return_pct: float = 0.0   # computed
    direction_correct: Optional[bool] = None  # computed

    def __post_init__(self):
        if self.entry_price > 0:
            self.actual_return_pct = (
                (self.next_day_price - self.entry_price) / self.entry_price
            ) * 100.0

        if self.decision == "HOLD":
            self.direction_correct = None  # HOLD is neutral
        elif self.decision == "BUY":
            self.direction_correct = self.next_day_price > self.entry_price
        elif self.decision == "SELL":
            self.direction_correct = self.next_day_price < self.entry_price
        else:
            self.direction_correct = None


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

    # PnL metrics
    total_return_pct: float = 0.0
    avg_return_per_trade_pct: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0

    # Risk metrics
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0

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
        trades: List of TradeResult from backtest run
        risk_free_rate_annual: Annualized risk-free rate for Sharpe calculation

    Returns:
        BacktestMetrics with all computed fields
    """
    m = BacktestMetrics(trades=trades, total_days=len(trades))

    if not trades:
        return m

    # --- Counts ---
    m.buy_count = sum(1 for t in trades if t.decision == "BUY")
    m.sell_count = sum(1 for t in trades if t.decision == "SELL")
    m.hold_count = sum(1 for t in trades if t.decision == "HOLD")

    # --- Directional Accuracy ---
    actionable = [t for t in trades if t.direction_correct is not None]
    m.correct_calls = sum(1 for t in actionable if t.direction_correct)
    m.incorrect_calls = sum(1 for t in actionable if not t.direction_correct)

    if actionable:
        m.directional_accuracy = m.correct_calls / len(actionable) * 100.0

    # --- PnL (only for actionable trades: BUY/SELL) ---
    pnl_trades = []
    for t in trades:
        if t.decision == "BUY":
            pnl_trades.append(t.actual_return_pct)
        elif t.decision == "SELL":
            # SELL profits when price goes down
            pnl_trades.append(-t.actual_return_pct)

    if pnl_trades:
        m.total_return_pct = sum(pnl_trades)
        m.avg_return_per_trade_pct = m.total_return_pct / len(pnl_trades)
        m.best_trade_pct = max(pnl_trades)
        m.worst_trade_pct = min(pnl_trades)

        # Win rate
        wins = [p for p in pnl_trades if p > 0]
        losses = [p for p in pnl_trades if p < 0]
        m.win_rate = len(wins) / len(pnl_trades) * 100.0 if pnl_trades else 0.0

        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        m.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe ratio (annualized, assuming ~252 trading days)
        if len(pnl_trades) >= 2:
            daily_rf = risk_free_rate_annual / 252.0
            excess = [r - daily_rf for r in pnl_trades]
            mean_excess = sum(excess) / len(excess)
            variance = sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0
            m.sharpe_ratio = (
                (mean_excess / std_dev) * math.sqrt(252) if std_dev > 0 else 0.0
            )

        # Max drawdown
        equity = 100.0  # start at 100
        peak = equity
        max_dd = 0.0
        for pnl in pnl_trades:
            equity *= 1 + pnl / 100.0
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
        m.max_drawdown_pct = max_dd

    # --- Confidence Calibration ---
    all_conf = [t.confidence for t in trades if t.confidence > 0]
    correct_conf = [t.confidence for t in actionable if t.direction_correct and t.confidence > 0]
    incorrect_conf = [t.confidence for t in actionable if not t.direction_correct and t.confidence > 0]

    m.avg_confidence = sum(all_conf) / len(all_conf) if all_conf else 0.0
    m.avg_confidence_correct = sum(correct_conf) / len(correct_conf) if correct_conf else 0.0
    m.avg_confidence_incorrect = sum(incorrect_conf) / len(incorrect_conf) if incorrect_conf else 0.0

    return m
