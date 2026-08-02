"""
TradingView Tool Provider for CMAOP Orchestrator.

Exposes TradingView technical analysis tools to CMAOP agents via the @tool decorator.
"""

from typing import Any, Dict
from orchestrator.sdk import tool
from tradingagents.dataflows.tradingview import fetch_tradingview_ta


@tool(
    name="get_tradingview_analysis",
    category="technical",
    description="Fetch technical indicators and summary recommendation (BUY/SELL/NEUTRAL) from TradingView.",
)
def get_tradingview_analysis(
    ticker: str,
    exchange: str = "BINANCE",
    screener: str = "crypto",
    interval: str = "1h",
) -> Dict[str, Any]:
    """
    Fetch TradingView technical analysis summary and indicator data.

    :param ticker: Symbol ticker (e.g. 'BTCUSDT', 'AAPL')
    :param exchange: Exchange name ('BINANCE', 'NASDAQ', 'COINBASE', etc.)
    :param screener: Screener market ('crypto', 'america', 'forex', etc.)
    :param interval: Timeframe interval ('1m', '5m', '15m', '1h', '4h', '1d', '1w')
    """
    return fetch_tradingview_ta(
        symbol=ticker,
        exchange=exchange,
        screener=screener,
        interval=interval,
    )
