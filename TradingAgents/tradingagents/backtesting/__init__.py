"""Backtesting package for TradingAgents.

Provides tools to measure agent directional accuracy, win rate,
and risk-adjusted returns on historical data.
"""

from .backtest_runner import BacktestRunner
from .metrics import BacktestMetrics
from .report import generate_report
