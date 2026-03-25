# TradingAgents/graph/conditional_logic.py

from typing import Set
from tradingagents.agents.utils.agent_states import AgentState


# ── Asset Class Detection ─────────────────────────────────────────────

# Canonical crypto tickers (base symbols, not pairs)
_KNOWN_CRYPTO_BASES: Set[str] = {
    "BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "BNB", "AVAX", "DOT",
    "MATIC", "LINK", "UNI", "AAVE", "LTC", "ATOM", "NEAR", "ARB", "OP",
    "APT", "SUI", "SEI", "TIA", "PEPE", "SHIB", "FIL", "INJ", "TRX",
}

# Known crypto quote suffixes
_CRYPTO_SUFFIXES = ("-USD", "-USDT", "-USDC", "-BTC", "-ETH", "/USD", "/USDT")

# Known equity exchanges (used as negative signal)
_EQUITY_EXCHANGES = (".NYSE", ".NASDAQ", ".LSE", ".TSE")


def is_crypto_ticker(ticker: str) -> bool:
    """Determine if a ticker represents a cryptocurrency.

    Uses a multi-signal approach rather than naive string matching:
    1. Check if ticker (stripped of pair suffixes) is in the known crypto set
    2. Check for crypto pair suffixes (-USD, -USDT, /USDT, etc.)
    3. Negative check: equity exchange markers

    Returns True if the ticker is identified as crypto, False otherwise.
    """
    upper = ticker.upper().strip()

    # Negative: explicit equity exchange
    if any(upper.endswith(ex) for ex in _EQUITY_EXCHANGES):
        return False

    # Strip common crypto pair suffixes to get the base
    base = upper
    for suffix in _CRYPTO_SUFFIXES:
        if upper.endswith(suffix):
            base = upper[: -len(suffix)]
            break

    # Also handle formats like BTCUSDT (no separator)
    for quote in ("USDT", "USDC", "USD", "BUSD"):
        if base.endswith(quote) and len(base) > len(quote):
            base = base[: -len(quote)]
            break

    # Check against known crypto bases
    if base in _KNOWN_CRYPTO_BASES:
        return True

    # Heuristic: has a crypto pair suffix → likely crypto
    if any(upper.endswith(s) for s in _CRYPTO_SUFFIXES):
        return True

    return False


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    # ── Generic analyst continuation (DRY) ────────────────────────────

    def _should_continue_analyst(self, state: AgentState, analyst_type: str) -> str:
        """Generic: route to tools if tool_calls present, else to Msg Clear."""
        messages = state["messages"]
        last_message = messages[-1]
        display = analyst_type.replace("_", " ").title()
        if last_message.tool_calls:
            return f"tools_{analyst_type}"
        return f"Msg Clear {display}"

    def should_continue_market(self, state: AgentState):
        return self._should_continue_analyst(state, "market")

    def should_continue_social(self, state: AgentState):
        return self._should_continue_analyst(state, "social")

    def should_continue_news(self, state: AgentState):
        return self._should_continue_analyst(state, "news")

    def should_continue_fundamentals(self, state: AgentState):
        return self._should_continue_analyst(state, "fundamentals")

    def should_continue_quant(self, state: AgentState):
        return self._should_continue_analyst(state, "quant")

    def should_continue_onchain(self, state: AgentState):
        return self._should_continue_analyst(state, "onchain")

    def should_continue_macro_geo(self, state: AgentState):
        return self._should_continue_analyst(state, "macro_geo")

    def should_continue_correlation(self, state: AgentState):
        return self._should_continue_analyst(state, "correlation")

    def should_continue_prediction_market(self, state: AgentState):
        return self._should_continue_analyst(state, "prediction_market")

    # ── Debate and Risk logic ─────────────────────────────────────────

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""
        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):
            return "Risk Judge"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
