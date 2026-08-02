"""
ICT (Inner Circle Trader / Smart Money Concepts) Analyst Agent for TradingAgents framework.
Performs quantitative analysis for Fair Value Gaps, Order Blocks, Liquidity Sweeps, and OTE Fibs.
"""

import logging
from typing import Any, Dict, Optional
from orchestrator.sdk.ict_agent import ict_agent_handler

logger = logging.getLogger(__name__)


def create_ict_analyst(llm: Optional[Any] = None, memory: Optional[Any] = None):
    """
    Factory function creating ICT analyst node for TradingAgents workflow graph.
    """
    async def ict_analyst_node(state: Dict[str, Any]) -> Dict[str, Any]:
        ticker = state.get("ticker", "BTCUSDT")
        logger.info("[ICTAnalyst] Running ICT Smart Money analysis for %s", ticker)

        # Delegate execution to ict_agent_handler
        report = await ict_agent_handler(state=state, bus=None, tools=None, ticker=ticker)

        # Format response into state updates
        messages = state.get("messages", [])
        messages.append({
            "role": "assistant",
            "name": "ICTAnalyst",
            "content": f"[ICT Smart Money Report for {ticker}]\n"
                       f"ICT Bias: {report.get('ict_bias')}\n"
                       f"Current Price: ${report.get('current_price')}\n"
                       f"Order Blocks: {len(report.get('order_blocks', []))} detected\n"
                       f"Fair Value Gaps: {len(report.get('fair_value_gaps', []))} detected\n"
                       f"In OTE Zone (61.8%-78.6%): {report.get('ote_zone', {}).get('in_ote_zone')}"
        })

        return {
            "messages": messages,
            "ict_report": report,
        }

    return ict_analyst_node
