"""ICT / Smart Money analyst: a plain (non-LLM) graph node fed by real OHLC candles."""

import logging
from typing import Any, Dict, Optional

from orchestrator.sdk.ict_agent import ict_agent_handler
from orchestrator.tools.tradingview_mcp_tools import _run_async

logger = logging.getLogger(__name__)


def _format(ticker: str, r: Dict[str, Any]) -> str:
    if r.get("data_quality") != "REAL_OHLC":
        return (f"ICT analysis unavailable for {ticker}: no real OHLC candles "
                f"(data_quality={r.get('data_quality')}). Do not infer anything from this section.")
    ote = r.get("ote_zone", {})
    return (f"[ICT Smart Money Report for {ticker}] data_quality=REAL_OHLC\n"
            f"ICT bias: {r.get('ict_bias')}\n"
            f"Current price: {r.get('current_price')}\n"
            f"Order blocks: {r.get('order_blocks', [])}\n"
            f"Fair value gaps: {r.get('fair_value_gaps', [])}\n"
            f"Liquidity sweeps: {r.get('liquidity_sweeps', [])}\n"
            f"OTE zone 61.8%-78.6%: {ote.get('fib_786')} - {ote.get('fib_618')} "
            f"(price inside: {ote.get('in_ote_zone')})")


def create_ict_analyst(llm: Optional[Any] = None, memory: Optional[Any] = None):
    """Graph node. `llm` is unused: every ICT concept is computed from candle geometry."""

    def ict_analyst_node(state: Dict[str, Any]) -> Dict[str, Any]:
        ticker = state.get("company_of_interest") or "BTCUSDT"
        try:
            report = _run_async(ict_agent_handler(state=None, bus=None, tools=None, ticker=ticker))
            text = _format(ticker, report)
        except Exception as exc:  # never take the whole analysis down
            logger.warning("[ICTAnalyst] failed for %s: %s", ticker, exc)
            text = f"ICT analysis unavailable for {ticker}: {exc}"
        return {"ict_report": text}  # no `messages`: safe under parallel fan-out

    return ict_analyst_node
