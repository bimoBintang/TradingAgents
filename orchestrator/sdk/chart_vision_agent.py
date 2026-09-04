"""
ChartVisionAgent — Specialized Multimodal Vision Agent for CMAOP.

Combines a TradingView chart screenshot with a real vision-LLM call to extract:
1. Primary Trend (BULLISH / BEARISH / SIDEWAYS)
2. Chart Patterns (Double Bottom, Head & Shoulders, Flag, Triangle, etc.)
3. Key Support & Resistance Levels
4. Visual Signal Confidence Score

Previously this handler never called any LLM at all — it re-labeled the same
RSI/EMA/SMA numbers already shown in the quantitative TA card via a
hardcoded lookup table (3 canned pattern names, confidence read off a fixed
table keyed by the TA recommendation string). CHART_VISION_SYSTEM_PROMPT
below was written but never sent anywhere. Fixed here: when a real
screenshot is available (image_b64 is populated — see
orchestrator/mcp/tradingview_mcp_client.py), it's actually sent to a
vision-capable LLM. When no screenshot is available at all, this returns an
honest "unavailable" report instead of a fabricated-but-plausible one.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Precise System Prompt for Multimodal Visual Chart Analysis
CHART_VISION_SYSTEM_PROMPT = """
You are a Senior Technical Analyst & Vision Specialist.
Analyze the provided TradingView chart screenshot and metadata for ticker {ticker} ({timeframe}).

Your analysis MUST return a structured JSON evaluation covering:
1. "primary_trend": "BULLISH" | "BEARISH" | "SIDEWAYS"
2. "chart_pattern": Detected pattern name or "No Distinct Pattern"
3. "key_support": Nearest support price level
4. "key_resistance": Nearest resistance price level
5. "visual_confidence": Confidence score between 0.0 and 1.0
6. "rationale": Concise explanation of visual price action and candle structure

Respond with ONLY the JSON object, no other text.
"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """Parse the model's JSON response, tolerating a ```json fenced block
    or stray leading/trailing prose around it (common LLM output quirks)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _unavailable_report(ticker: str, timeframe: str, reason: str) -> Dict[str, Any]:
    """Honest empty state — no screenshot / no vision call succeeded.

    Deliberately does NOT invent a plausible-looking trend/pattern/
    confidence the way the old hardcoded lookup table did.
    """
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "primary_trend": None,
        "chart_pattern": None,
        "key_support": None,
        "key_resistance": None,
        "visual_confidence": None,
        "recommendation": None,
        "mode": "UNAVAILABLE",
        "rationale": reason,
    }


def _run_vision_llm(image_b64: str, ticker: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Send the screenshot to a vision-capable LLM and parse its structured
    JSON response. Returns None (never raises) on any failure — missing
    API key, network error, malformed response — so the caller can fall
    back cleanly instead of crashing the whole analysis endpoint.
    """
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.llm_clients import create_llm_client
        from langchain_core.messages import HumanMessage

        provider = DEFAULT_CONFIG.get("smart_think_llm_provider", DEFAULT_CONFIG.get("llm_provider", "anthropic"))
        model = DEFAULT_CONFIG.get("smart_think_llm", "claude-sonnet-4-6")
        client = create_llm_client(provider=provider, model=model)
        llm = client.get_llm()

        prompt = CHART_VISION_SYSTEM_PROMPT.format(ticker=ticker, timeframe=timeframe)
        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ])

        response = llm.invoke([message])
        content = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _extract_json(content)
        if parsed is None:
            logger.warning("[ChartVisionAgent] LLM response wasn't valid JSON: %s", content[:200])
            return None
        return parsed

    except Exception as e:
        logger.warning("[ChartVisionAgent] Vision LLM call failed: %s", e)
        return None


async def chart_vision_agent_handler(state, bus, tools, **kwargs) -> Dict[str, Any]:
    """
    Handler function for ChartVisionAgent in CMAOP orchestrator.

    Mode selection:
      1. Real CDP screenshot (tv_take_screenshot returns mode="LIVE_CDP_DESKTOP"
         with real image bytes) -> vision LLM call on that image.
      2. No CDP / CDP screenshot failed -> caller (api/routers/tradingview.py)
         may supply a client-side chart screenshot via kwargs["fallback_image_b64"]
         (see the /vision-fallback endpoint) -> vision LLM call on THAT image.
      3. Neither available -> honest "UNAVAILABLE" report, not a fabricated one.
    """
    ticker = getattr(state, "ticker", "BTCUSDT")
    timeframe = kwargs.get("timeframe", "1h")

    resolved_tools = tools.get_for_agent(categories=["chart_visual", "technical"])

    # 1. Fetch live or fallback chart info (still used for the "mode" label
    #    and as a last-resort text-only signal if vision itself is unavailable)
    chart_info = {}
    if "tv_get_chart_info" in resolved_tools:
        chart_info = resolved_tools["tv_get_chart_info"](ticker=ticker, timeframe=timeframe)

    # 2. Capture screenshot (live CDP or fallback quantitative summary —
    #    the fallback path returns image_b64=None, see tradingview_mcp_client.py)
    screenshot_res = {}
    if "tv_take_screenshot" in resolved_tools:
        screenshot_res = resolved_tools["tv_take_screenshot"](ticker=ticker, timeframe=timeframe)

    image_b64 = screenshot_res.get("image_b64") or kwargs.get("fallback_image_b64")
    source_mode = screenshot_res.get("mode", "FALLBACK_QUANTITATIVE_TA") if screenshot_res.get("image_b64") \
        else ("CLIENT_CHART_SCREENSHOT" if kwargs.get("fallback_image_b64") else "NO_SCREENSHOT")

    report: Dict[str, Any]
    if image_b64:
        vision_result = _run_vision_llm(image_b64, ticker, timeframe)
        if vision_result is not None:
            report = {
                "ticker": ticker,
                "timeframe": timeframe,
                "primary_trend": vision_result.get("primary_trend"),
                "chart_pattern": vision_result.get("chart_pattern"),
                "key_support": vision_result.get("key_support"),
                "key_resistance": vision_result.get("key_resistance"),
                "visual_confidence": vision_result.get("visual_confidence"),
                "recommendation": screenshot_res.get("recommendation", chart_info.get("recommendation")),
                "mode": source_mode,
                "rationale": vision_result.get("rationale", ""),
            }
        else:
            report = _unavailable_report(
                ticker, timeframe,
                "A chart screenshot was available but the vision-LLM analysis failed "
                "(see server logs — commonly a missing/invalid API key). No trend/pattern "
                "is reported rather than guessing.",
            )
    else:
        report = _unavailable_report(
            ticker, timeframe,
            "No chart screenshot available (TradingView Desktop CDP not connected, and no "
            "client-side chart screenshot was supplied). Quantitative TA (RSI/MACD/EMA/SMA) "
            "is still available separately — this card specifically needs a real image to analyze.",
        )

    # Store analysis in StateManager for RiskManager & TraderAgent access
    state.set("analysis", "chart_vision_report", report, writer="chart_vision_agent")
    logger.info(
        "[ChartVisionAgent] Analysis complete for %s -> mode=%s trend=%s",
        ticker, report["mode"], report.get("primary_trend"),
    )

    return report
