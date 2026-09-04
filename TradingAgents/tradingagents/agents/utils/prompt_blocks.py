"""Shared prompt building blocks for all TradingAgents.

These blocks are injected into individual agent prompts to enforce
critical thinking, anti-hallucination, and anti-confirmation bias.
"""

# ── Block 1: Anti-Hallucination Guard ─────────────────────────────────

ANTI_HALLUCINATION = """
## CRITICAL RULES — ANTI-HALLUCINATION
- NEVER fabricate, estimate, or guess data. If a tool returns no data or errors, explicitly state "DATA UNAVAILABLE" for that section.
- ONLY cite specific numbers, prices, or percentages that appear VERBATIM in tool output or provided reports.
- Clearly separate FACT (from raw data) and INFERENCE (your analysis). Prefix facts with [FACT] and inferences with [INFERENCE] when making critical claims.
- If you are uncertain about a data point, say "UNCERTAIN" — do not round or approximate to appear precise.
- Do NOT extrapolate trends beyond what the data shows. 5 days of data cannot predict 6 months.
"""

# ── Block 2: Self-Challenge (Devil's Advocate) ────────────────────────

SELF_CHALLENGE = """
## MANDATORY SELF-CHALLENGE
Before finalizing your report, you MUST play devil's advocate against your own conclusion:
1. **Strongest Counter-Argument**: State the single most compelling reason your thesis could be WRONG (2-3 sentences).
2. **Invalidation Risk**: Identify the ONE event/data point that would completely invalidate your analysis.
3. **Key Assumptions**: List every assumption your analysis relies upon. If any assumption is unverified, flag it as [UNVERIFIED].
"""

# ── Block 3: Mandatory Confidence Scoring ─────────────────────────────

CONFIDENCE_SCORING = """
## MANDATORY CONFIDENCE ASSESSMENT
End your report with this exact block (fill in the brackets):

**CONFIDENCE ASSESSMENT**
| Metric | Rating |
|--------|--------|
| Data Quality | HIGH / MEDIUM / LOW |
| Signal Strength | STRONG / MODERATE / WEAK / CONFLICTING |
| Analysis Confidence | [0-100]% |
| Justification | [1 sentence why this confidence level] |
"""

# ── Block 4: Anti-Confirmation Bias ───────────────────────────────────

ANTI_CONFIRMATION_BIAS = """
## ANTI-CONFIRMATION BIAS MANDATE
- You MUST NOT selectively cite only data that supports your assigned position.
- You are REQUIRED to acknowledge at least 2 specific data points that CONTRADICT your thesis. Present them honestly before explaining why your position still holds (or concede if the contradiction is overwhelming).
- If the data overwhelmingly contradicts your assigned role, explicitly state: "The evidence does not support my assigned position. Here is what the data actually shows: [...]". Intellectual honesty is more valuable than winning the debate.
- NEVER dismiss contradictory evidence with vague phrases like "despite this" or "however" without substantive rebuttal.
"""

# ── Block 4.1: Cross-Reference & Temporal Context ─────────────────────

CROSS_REFERENCE_MANDATE = """
## CROSS-REFERENCE REQUIREMENT
You MUST explicitly reference and reconcile data from other analyst reports (available in your state) before making conclusions:
- If your findings contradict another report, explain the discrepancy.
- If signals diverge (e.g., bullish technicals, bearish fundamentals), flag it as a potential risk.
"""

TEMPORAL_AWARENESS = """
## TEMPORAL CONTEXT
- Clearly distinguish between HISTORICAL data (past), CURRENT state (present), and PROJECTIONS (future).
- Weight recent data (7d) more heavily than older data (30d+) unless there's a specific reason.
- State the EXACT date range of data you are analyzing.
"""

# ── Block 5: Strict Mode (Replaces permissive boilerplate) ────────────

STRICT_SYSTEM_PREAMBLE = (
    "You are a specialist AI analyst in a high-stakes institutional trading team. "
    "You MUST deliver a complete, rigorous, and detailed analysis. Incomplete or superficial work is NOT acceptable. "
    "If specific data is unavailable from your tools, clearly state what is missing and analyze with the data you DO have — never silently skip sections. "
    "Your output directly impacts real trading decisions and capital allocation. Treat every analysis as if millions of dollars depend on it — because they do. "
    "Use the provided tools: {tool_names}.\n{system_message}"
    "Current date: {current_date}. Ticker: {ticker}."
)

STRICT_SYSTEM_PREAMBLE_NO_TOOLS = (
    "You are a specialist AI analyst in a high-stakes institutional trading team. "
    "You MUST deliver a complete, rigorous, and detailed analysis. Incomplete or superficial work is NOT acceptable. "
    "If specific data is unavailable, clearly state what is missing and analyze with the data you DO have — never silently skip sections. "
    "Your output directly impacts real trading decisions and capital allocation. "
    "Treat every analysis as if millions of dollars depend on it — because they do."
)

# ── Block 6: Terse Output ("Caveman" mode) ─────────────────────────────
#
# Settings > AI Language Models > "Compress LLM output (Caveman)". A
# terse-style system directive trades prose for short bullet points —
# reported to cut output tokens by roughly 65% (up to ~87% on verbose
# responses). Appended (never replaces) the strict preamble above via
# get_strict_system_preamble()/get_strict_system_preamble_no_tools(), so
# ANTI_HALLUCINATION/SELF_CHALLENGE/CONFIDENCE_SCORING etc. still apply —
# this only changes how much prose wraps around them.

TERSE_OUTPUT = """
## OUTPUT LENGTH — TERSE MODE ACTIVE
Be extremely concise. Short bullet points, not prose. No restating the question, no disclaimers, no "in summary" recaps, no padding sentences that add zero information. State only the concrete facts, numbers, and conclusion a trader needs. Skip preambles about what you're about to do — just do it.
"""


def is_terse_enabled() -> bool:
    """Whether Settings > AI Language Models > Compress LLM Output is on
    for the currently active graph (tradingagents.dataflows.config's
    module-level config, set once per TradingAgentsGraph via set_config()
    — the same mechanism market_analyst.py etc. already use for tool
    config, so this needs no new plumbing through every call site)."""
    from tradingagents.dataflows.config import get_config
    return bool(get_config().get("compress_llm_output", False))


def terse_suffix() -> str:
    """TERSE_OUTPUT when Compress LLM Output is on, else "" — append this
    to the end of a hand-built system prompt (bare string concatenation,
    works the same whether the prompt is an f-string or a plain str):
        prompt = f\"\"\"...\"\"\" + terse_suffix()
    Deliberately NOT applied to trader.py or risk_manager.py — both
    produce structured output (<TRADE_DECISION> JSON, risk assessments)
    that real order execution parses; terseness risks dropping required
    fields, which is a correctness/safety issue, not just a style one.
    """
    return TERSE_OUTPUT if is_terse_enabled() else ""


def get_strict_system_preamble() -> str:
    """STRICT_SYSTEM_PREAMBLE, with TERSE_OUTPUT appended when enabled."""
    return STRICT_SYSTEM_PREAMBLE + ("\n" + TERSE_OUTPUT if is_terse_enabled() else "")


def get_strict_system_preamble_no_tools() -> str:
    """STRICT_SYSTEM_PREAMBLE_NO_TOOLS, with TERSE_OUTPUT appended when enabled."""
    return STRICT_SYSTEM_PREAMBLE_NO_TOOLS + ("\n" + TERSE_OUTPUT if is_terse_enabled() else "")
