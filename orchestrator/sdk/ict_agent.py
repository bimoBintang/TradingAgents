"""
ICTAgent Subagent Handler — Inner Circle Trader & Smart Money Concepts Specialist.

Analyzes institutional price structure, Fair Value Gaps, Order Blocks, Liquidity Sweeps,
and calculates the overall ICT Smart Money Bias for the orchestrator state manager.
"""

import logging
from typing import Any, Dict
from orchestrator.tools.ict_tool import analyze_ict_concepts

logger = logging.getLogger(__name__)


async def ict_agent_handler(state, bus, tools, ticker: str = "BTCUSDT", timeframe: str = "1h") -> Dict[str, Any]:
    """
    Handler function for ICTAgent subagent.
    Runs analyze_ict_concepts, publishes report to bus, and updates state.
    """
    logger.info("[ICTAgent] Starting Smart Money analysis for %s (%s)", ticker, timeframe)

    try:
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
