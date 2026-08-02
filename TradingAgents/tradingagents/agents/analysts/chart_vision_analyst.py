"""
ChartVision Analyst Agent for TradingAgents framework.
Integrates multimodal LLM vision analysis for TradingView charts.
"""

import logging
from typing import Any, Dict, Optional
from orchestrator.sdk.chart_vision_agent import chart_vision_agent_handler

logger = logging.getLogger(__name__)


def create_chart_vision_analyst(llm: Optional[Any] = None, memory: Optional[Any] = None):
    """
    Factory function creating ChartVision analyst node for TradingAgents workflow graph.
    """
    async def chart_vision_node(state: Dict[str, Any]) -> Dict[str, Any]:
        ticker = state.get("ticker", "BTCUSDT")
        timeframe = state.get("timeframe", "1h")
        logger.info("[ChartVisionAnalyst] Running multimodal chart vision analysis for %s (%s)", ticker, timeframe)

        # Delegate execution to chart_vision_agent_handler
        report = await chart_vision_agent_handler(state=state, bus=None, tools=None, timeframe=timeframe)
        
        # Format response into state updates
        messages = state.get("messages", [])
        messages.append({
            "role": "assistant",
            "name": "ChartVisionAnalyst",
            "content": f"[ChartVision Analysis Report for {ticker}]\n"
                       f"Primary Trend: {report.get('primary_trend')}\n"
                       f"Chart Pattern: {report.get('chart_pattern')}\n"
                       f"Visual Confidence: {report.get('visual_confidence')}\n"
                       f"Support/Resistance: ${report.get('key_support')} / ${report.get('key_resistance')}"
        })

        return {
            "messages": messages,
            "chart_vision_report": report,
        }

    return chart_vision_node
