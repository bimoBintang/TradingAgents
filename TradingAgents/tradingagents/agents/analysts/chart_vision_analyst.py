"""ChartVision analyst: a plain graph node (vision LLM or quantitative fallback inside the handler)."""

import logging
from typing import Any, Dict, Optional

from orchestrator.sdk import create_trading_orchestrator, chart_vision_agent_handler
from orchestrator.tools.tradingview_mcp_tools import _run_async

logger = logging.getLogger(__name__)


def _lv(v):
    return "n/a" if v is None else f"${v}"


def _format(ticker: str, r: Dict[str, Any]) -> str:
    if r.get("mode") == "UNAVAILABLE":
        return (f"ChartVision unavailable for {ticker}: {r.get('rationale')} "
                "Do not infer anything from this section.")
    return (f"[ChartVision Report for {ticker}] mode={r.get('mode')}\n"
            f"Primary trend: {r.get('primary_trend')}\n"
            f"Chart pattern: {r.get('chart_pattern') or 'n/a'}\n"
            f"Visual confidence: {r.get('visual_confidence') if r.get('visual_confidence') is not None else 'n/a'}\n"
            f"Support/Resistance: {_lv(r.get('key_support'))} / {_lv(r.get('key_resistance'))}\n"
            f"TA recommendation: {r.get('recommendation')}\n"
            f"Basis: {r.get('rationale')}")


def create_chart_vision_analyst(llm: Optional[Any] = None, memory: Optional[Any] = None):
    """Graph node. `llm` is unused: the handler picks `vision_llm` itself."""

    def chart_vision_node(state: Dict[str, Any]) -> Dict[str, Any]:
        ticker = state.get("company_of_interest") or "BTCUSDT"
        try:
            orch = create_trading_orchestrator(ticker=ticker, topology="pipeline")
            report = _run_async(chart_vision_agent_handler(
                orch.state, orch.bus, orch.tools, timeframe="1h"))
            text = _format(ticker, report)
        except Exception as exc:
            logger.warning("[ChartVisionAnalyst] failed for %s: %s", ticker, exc)
            text = f"ChartVision unavailable for {ticker}: {exc}"
        return {"chart_vision_report": text}

    return chart_vision_node
