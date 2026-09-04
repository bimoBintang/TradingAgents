"""
ICTAgent Subagent Handler — Inner Circle Trader & Smart Money Concepts Specialist.

Analyzes institutional price structure, Fair Value Gaps, Order Blocks, Liquidity Sweeps,
and calculates the overall ICT Smart Money Bias for the orchestrator state manager.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
from orchestrator.tools.ict_tool import analyze_ict_concepts

logger = logging.getLogger(__name__)

# ICT structure needs enough history for swing/ATR context, but not so much
# that stale regime dominates. ~250 bars is a common working window.
_ICT_LOOKBACK_BARS = 250


def _fetch_ohlc(ticker: str, timeframe: str) -> Optional[Dict[str, list]]:
    """Fetch REAL OHLC candles for ICT analysis.

    Every ICT concept is candle geometry (wick penetrations, body/ATR
    displacement, gaps between extremes), so without genuine highs/lows
    the engine analyzes an artifact. This handler previously called
    analyze_ict_concepts(ticker=...) with no price data at all, which
    silently fell through to the sine-wave placeholder — meaning the
    ict_bias reported to the agents was derived from a generated waveform,
    not the market. (TVExecutionGuard is designed to consume ict_bias too,
    but is currently not wired into any execution path.)

    Returns None on failure; the caller then surfaces the degraded
    data_quality rather than pretending the read is valid.
    """
    try:
        from tradingagents.dataflows.ccxt_ohlcv import fetch_ohlcv
        candles = fetch_ohlcv("binance", ticker, timeframe=timeframe, limit=_ICT_LOOKBACK_BARS)
        if candles and len(candles) >= 15:
            return {
                "closes": [c["close"] for c in candles],
                "opens": [c["open"] for c in candles],
                "highs": [c["high"] for c in candles],
                "lows": [c["low"] for c in candles],
            }
    except Exception as exc:
        logger.warning("[ICTAgent] OHLC fetch failed for %s: %s", ticker, exc)
    return None


async def ict_agent_handler(state, bus, tools, ticker: str = "BTCUSDT", timeframe: str = "1h") -> Dict[str, Any]:
    """
    Handler function for ICTAgent subagent.
    Runs analyze_ict_concepts, publishes report to bus, and updates state.
    """
    logger.info("[ICTAgent] Starting Smart Money analysis for %s (%s)", ticker, timeframe)

    try:
        ohlc = await asyncio.to_thread(_fetch_ohlc, ticker, timeframe)
        if ohlc:
            ict_report = analyze_ict_concepts(
                ticker=ticker,
                prices=ohlc["closes"],
                opens=ohlc["opens"],
                highs=ohlc["highs"],
                lows=ohlc["lows"],
            )
        else:
            ict_report = analyze_ict_concepts(ticker=ticker)
    except Exception as exc:
        logger.error("[ICTAgent] Error analyzing ICT concepts for %s: %s", ticker, exc)
        ict_report = {
            "ticker": ticker,
            "current_price": 0.0,
            "ict_bias": "NEUTRAL",
            "fair_value_gaps": [],
            "order_blocks": [],
            "liquidity_sweeps": [],
            "ote_zone": {"fib_618": 0.0, "fib_786": 0.0, "in_ote_zone": False},
            "error": str(exc),
        }

    # Store report in state manager
    if hasattr(state, "set"):
        state.set("analysis", "ict_report", ict_report)

    # Publish notification event to bus
    if hasattr(bus, "publish"):
        from orchestrator.core.agent_bus import Message
        await bus.publish(Message(
            topic="analysis.ict",
            sender="ict_agent",
            payload={
                "ticker": ticker,
                "ict_bias": ict_report.get("ict_bias", "NEUTRAL"),
                "order_blocks_found": len(ict_report.get("order_blocks", [])),
                "fvgs_found": len(ict_report.get("fair_value_gaps", [])),
            }
        ))

    logger.info("[ICTAgent] Analysis completed for %s. Bias: %s", ticker, ict_report.get("ict_bias"))
    return ict_report
