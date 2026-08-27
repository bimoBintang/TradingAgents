from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.prompt_blocks import (
    ANTI_HALLUCINATION, ANTI_CONFIRMATION_BIAS, CROSS_REFERENCE_MANDATE, TEMPORAL_AWARENESS, SELF_CHALLENGE, CONFIDENCE_SCORING, STRICT_SYSTEM_PREAMBLE,
)

from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators
from tradingagents.agents.utils.advanced_tools import get_options_chain
from tradingagents.agents.utils.fibonacci_tools import get_fibonacci_levels
from tradingagents.agents.utils.smc_tools import (
    get_fair_value_gaps, get_inversion_fvgs, get_liquidity_sweeps,
    get_order_flow, get_anchored_vwap, get_volume_profile,
)


def create_quant_analyst(llm):
    """Create a Quantitative Analyst node for the LangGraph pipeline.

    Performs advanced statistical analysis: volatility regime detection,
    Z-score mean reversion, Hurst exponent estimation, options-implied metrics,
    Fibonacci levels, and Smart Money Concepts (FVG, IFVG, Liquidity Sweeps,
    Order Flow, Anchored VWAP, Volume Profile).
    """

    def quant_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        tools = [
            get_stock_data, get_indicators, get_options_chain, get_fibonacci_levels,
            get_fair_value_gaps, get_inversion_fvgs, get_liquidity_sweeps,
            get_order_flow, get_anchored_vwap, get_volume_profile,
        ]

        system_message = (
            "You are an elite Quantitative Analyst at a top-tier hedge fund. "
            "Your role is to apply advanced mathematical and statistical methods to financial data. "
            "You MUST produce a comprehensive quantitative report covering:\n\n"
            "1. **Volatility Regime**: Classify as Low/Medium/High/Extreme using recent price "
            "standard deviation vs historical norms. Calculate realized volatility (20-day annualized).\n"
            "2. **Mean Reversion Signal**: Compute the Z-score of current price vs 50-day SMA. "
            "Z > 2 = overbought, Z < -2 = oversold. State probability of mean reversion.\n"
            "3. **Trend Strength (Hurst Exponent Estimate)**: Based on autocorrelation of returns, "
            "estimate if the series is trending (H>0.5) or mean-reverting (H<0.5).\n"
            "4. **Options-Implied Signals** (if available): Put/Call ratio, IV skew, "
            "and what they imply about institutional positioning.\n"
            "5. **Fibonacci Support/Resistance**: Use the fibonacci tool to compute key retracement "
            "levels (23.6%, 38.2%, 50%, 61.8%, 78.6%). Identify where current price sits relative to "
            "these levels. Note any confluence with SMA or Bollinger Band levels.\n"
            "6. **Fibonacci Extension Targets**: If a clear trend is present, project profit targets "
            "using 127.2%, 161.8%, and 261.8% extension levels.\n"
            "7. **Fair Value Gaps**: Use the FVG tool. Report unfilled bullish/bearish FVGs near "
            "current price. Unfilled FVGs act as magnets — price tends to return to fill them. "
            "Note confluence with Fibonacci levels.\n"
            "8. **Inversion FVGs**: Check for FVGs that have been fully breached and flipped. "
            "Bullish FVG inverted = new resistance. Bearish FVG inverted = new support. "
            "Filled/invalidated FVGs should NOT be treated as active zones.\n"
            "9. **Liquidity Sweeps**: Use the liquidity sweep tool. Sweeps of swing highs = "
            "institutional selling (buy-side liquidity taken). Sweeps of swing lows = "
            "institutional buying (sell-side liquidity taken). Combine with Order Flow for confirmation.\n"
            "10. **Order Flow Analysis**: Use the order flow tool. Report cumulative delta direction. "
            "Price up + delta down = bearish divergence. Sweeps + delta alignment = high-conviction signal.\n"
            "11. **Anchored VWAP**: Use the VWAP tool. Price > VWAP = bullish context. "
            "Price < VWAP = bearish context. Deviation > 2% = potential mean-reversion setup.\n"
            "12. **Volume Profile**: Use the volume profile tool. POC = 'fair value'. "
            "Trading above POC = bullish. VAH = resistance, VAL = support. "
            "Price at VAH/VAL with opposing order flow = high-probability reversal.\n"
            "13. **Statistical Edge Summary**: A clear 1–2 sentence conclusion on the "
            "quantitative edge (or lack thereof) for this asset.\n\n"
            "CRITICAL: Cite specific price levels from tool output (e.g., 'FVG zone at "
            "$185.20–$187.40', 'POC at $192.50'). Never invent price levels. If a tool "
            "returns insufficient_data, state that the data was unavailable and skip.\n\n"
            "Append a Markdown table summarizing key metrics at the end of your report."
            + ANTI_HALLUCINATION
            + ANTI_CONFIRMATION_BIAS
            + CROSS_REFERENCE_MANDATE
            + TEMPORAL_AWARENESS, ANTI_CONFIRMATION_BIAS, CROSS_REFERENCE_MANDATE, TEMPORAL_AWARENESS
            + SELF_CHALLENGE
            + CONFIDENCE_SCORING
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                STRICT_SYSTEM_PREAMBLE,
            ),
            MessagesPlaceholder(variable_name="messages"),
        ])

        prompt = prompt.partial(
            system_message=system_message,
            tool_names=", ".join([t.name for t in tools]),
            current_date=current_date,
            ticker=ticker,
        )

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "quant_report": report,
        }

    return quant_analyst_node
