# TradingAgents/graph/signal_processing.py

import json
from langchain_openai import ChatOpenAI
from tradingagents.execution.order_models import TradeDecision, TradeAction, OrderType


SIGNAL_EXTRACTION_PROMPT = """You are an expert signal extraction system. Analyze the provided financial report / trading decision and extract a structured trading decision.

You MUST respond with ONLY a valid JSON object matching this exact schema (no extra text, no markdown):

{
    "action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
    "ticker": "<ticker symbol>",
    "confidence_score": <float 0.0 to 1.0>,
    "quantity_pct": <float 0.0 to 1.0 — recommended portfolio allocation>,
    "order_type": "MARKET" | "LIMIT",
    "stop_loss_pct": <float 0.0 to 1.0 or null — e.g. 0.05 for 5% stop-loss>,
    "take_profit_pct": <float 0.0 to 1.0 or null — e.g. 0.10 for 10% take-profit>,
    "leverage": <int 1-125, default 1 for spot>,
    "position_side": "LONG" | "SHORT",
    "margin_type": "isolated" | "cross",
    "reasoning": "<brief reasoning for the decision>",
    "key_factors": ["<factor 1>", "<factor 2>", ...],
    "risk_reward_ratio": <float or null>,
    "time_horizon": "intraday" | "short_term" | "medium_term" | "long_term"
}

Rules:
- confidence_score: How confident the analysts are. 0.8+ = very strong conviction.
- quantity_pct: Suggest based on conviction. STRONG_BUY → 0.15-0.25, BUY → 0.05-0.15, HOLD/SELL → 0.0
- stop_loss_pct: Always set for BUY/SELL. Typical: 0.03-0.08.
- take_profit_pct: Always set for BUY/SELL. Should be > stop_loss_pct for good risk/reward.
- key_factors: Top 3-5 factors.
- leverage: Extract from the report. Default to 1 if not mentioned (spot trading).
- position_side: LONG for bullish, SHORT for bearish. Default LONG.
- margin_type: Default "isolated". Set "cross" only if explicitly mentioned.
- If the decision is HOLD, set quantity_pct to 0.0 and stop_loss/take_profit to null.
"""


class SignalProcessor:
    """Processes trading signals to extract structured, actionable decisions."""

    def __init__(self, quick_thinking_llm: ChatOpenAI):
        """Initialize with an LLM for processing."""
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str, ticker: str = "",
                       execution_strategy: str = "") -> str:
        """Process a full trading signal to extract the core decision.

        Returns the structured JSON string of the TradeDecision, or a simple
        BUY/SELL/HOLD string as fallback if structured parsing fails.

        Args:
            full_signal: Complete trading signal text from the risk judge
            ticker: The ticker symbol being analyzed
            execution_strategy: Optional execution strategy from Execution Optimizer

        Returns:
            JSON string of TradeDecision, or simple action string as fallback
        """
        # Combine signal with execution strategy context if available
        combined_signal = full_signal
        if execution_strategy:
            combined_signal += f"\n\nExecution Strategy Optimization:\n{execution_strategy}"

        # Try structured extraction
        trade_decision = self.extract_structured_decision(combined_signal, ticker)
        if trade_decision:
            return trade_decision.model_dump_json(indent=2)

        # Fallback: extract simple action
        return self._extract_simple_action(full_signal, ticker)

    def extract_structured_decision(
        self, full_signal: str, ticker: str = ""
    ) -> TradeDecision | None:
        """Extract a structured TradeDecision from the signal text.
        
        Args:
            full_signal: Complete trading signal text
            ticker: The ticker symbol being analyzed
            
        Returns:
            TradeDecision object or None if parsing fails
        """
        messages = [
            ("system", SIGNAL_EXTRACTION_PROMPT),
            ("human", f"Ticker: {ticker}\n\nFull Trading Report:\n{full_signal}"),
        ]

        try:
            result = self.quick_thinking_llm.invoke(messages).content

            # Clean up the response — strip markdown fences if present
            cleaned = result.strip()
            if cleaned.startswith("```"):
                # Remove ```json ... ``` wrapper
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)

            parsed = json.loads(cleaned)

            # Ensure ticker is set
            if not parsed.get("ticker") and ticker:
                parsed["ticker"] = ticker

            return TradeDecision(**parsed)

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"[SignalProcessor] Structured extraction failed: {e}")
            return None

    def _extract_simple_action(self, full_signal: str, ticker: str = "") -> str:
        """Fallback: Extract simple action and wrap in a safe TradeDecision."""
        messages = [
            (
                "system",
                "You are an efficient assistant. Extract the investment decision: SELL, BUY, or HOLD. "
                "Provide only the extracted decision (SELL, BUY, or HOLD) as your output.",
            ),
            ("human", full_signal),
        ]
        action = self.quick_thinking_llm.invoke(messages).content.strip().upper()

        if action not in ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"]:
            action = "HOLD"

        decision = TradeDecision(
            action=action,
            ticker=ticker,
            confidence_score=0.5,  # Conservative default
            quantity_pct=0.05 if "BUY" in action else 0.0,
            order_type="MARKET",
            stop_loss_pct=0.05 if action != "HOLD" else None,
            take_profit_pct=0.10 if action != "HOLD" else None,
            reasoning="Fallback decision extraction.",
        )
        return decision.model_dump_json(indent=2)
