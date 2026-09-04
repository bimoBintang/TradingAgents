"""Backtesting package for TradingAgents.

Provides tools to measure agent directional accuracy, win rate,
and risk-adjusted returns on historical data — with realistic exits
(stop-loss / take-profit / holding period) and round-trip costs, plus
deterministic baselines to compare the agent stack against.
"""

from .backtest_runner import BacktestRunner
from .metrics import BacktestMetrics, TradeResult
from .report import generate_report
from .baselines import (
    buy_and_hold_decision,
    make_sma_crossover_decision,
    compare_against_baselines,
)
from .walk_forward import (
    walk_forward_analysis,
    format_walk_forward_report,
    WalkForwardResult,
)
from .ict_measurement import (
    measure_ict_on_ticker,
    format_measurement_report,
    ICTMeasurementResult,
)

__all__ = [
    "BacktestRunner",
    "BacktestMetrics",
    "TradeResult",
    "generate_report",
    # Baselines — the bar the agent stack has to clear
    "buy_and_hold_decision",
    "make_sma_crossover_decision",
    "compare_against_baselines",
    # Walk-forward — measures overfitting rather than hiding it
    "walk_forward_analysis",
    "format_walk_forward_report",
    "WalkForwardResult",
    # ICT/SMC empirical validation
    "measure_ict_on_ticker",
    "format_measurement_report",
    "ICTMeasurementResult",
]
