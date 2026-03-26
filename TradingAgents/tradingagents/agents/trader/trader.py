import functools
import json
from tradingagents.agents.utils.prompt_blocks import (
    ANTI_HALLUCINATION, SELF_CHALLENGE, CONFIDENCE_SCORING,
)


TRADER_SYSTEM_PROMPT = """You are a trading agent analyzing market data to make investment decisions. You receive comprehensive analysis from a team of analysts and must make a specific trading recommendation.

{portfolio_context}

You MUST end your response with a structured JSON block wrapped in <TRADE_DECISION> tags:

<TRADE_DECISION>
{{
    "action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
    "confidence_score": <float 0.0 to 1.0>,
    "quantity_pct": <float 0.0 to 1.0 — percentage of portfolio to allocate>,
    "order_type": "MARKET" | "LIMIT",
    "stop_loss_pct": <float or null — e.g. 0.05 for 5%>,
    "take_profit_pct": <float or null — e.g. 0.10 for 10%>,
    "leverage": <int 1-125, default 1 for spot>,
    "position_side": "LONG" | "SHORT",
    "margin_type": "isolated" | "cross",
    "reasoning": "<concise reasoning>",
    "key_factors": ["<factor1>", "<factor2>", "<factor3>"],
    "risk_reward_ratio": <float or null>,
    "time_horizon": "intraday" | "short_term" | "medium_term" | "long_term"
}}
</TRADE_DECISION>

Guidelines for position sizing:
- STRONG_BUY: 0.15 to 0.25 of portfolio
- BUY: 0.05 to 0.15 of portfolio
- HOLD: 0.0 (no new position)
- SELL: close existing position or 0.0 if no position
- STRONG_SELL: close all existing positions for this ticker

Futures Trading Guidelines:
- Set leverage based on conviction and volatility (1x = spot, 3-5x = moderate, 10x+ = aggressive)
- position_side: LONG for bullish, SHORT for bearish
- Default to "isolated" margin for safety; use "cross" only for hedged positions
- Higher leverage = smaller quantity_pct (auto-adjusted by risk controller)
- If trading spot, set leverage=1, position_side="LONG", margin_type="isolated"

Always set stop_loss_pct (e.g. 0.03-0.08) and take_profit_pct for actionable trades. Ensure risk_reward_ratio > 1.5 for good trade quality.

Consider the current portfolio state when making decisions. If you already have a large position, consider that in your sizing. Do not over-allocate.

Utilize lessons from past decisions to learn from mistakes:
{past_memories}

IMPORTANT: Always end with the <TRADE_DECISION> JSON block. The JSON must be valid.

""" + ANTI_HALLUCINATION + """

""" + SELF_CHALLENGE + """

""" + CONFIDENCE_SCORING


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        # Build portfolio context string
        portfolio_context = ""
        portfolio_state = state.get("portfolio_state")
        if portfolio_state:
            portfolio_context = portfolio_state
        else:
            portfolio_context = "No portfolio information available. Assume default $10,000 paper portfolio."

        system_prompt = TRADER_SYSTEM_PROMPT.format(
            past_memories=past_memory_str,
            portfolio_context=portfolio_context,
        )

        context = {
            "role": "user",
            "content": (
                f"Based on a comprehensive analysis by a team of analysts, here is an investment plan "
                f"tailored for {company_name}. This plan incorporates insights from current technical "
                f"market trends, macroeconomic indicators, and social media sentiment.\n\n"
                f"Proposed Investment Plan: {investment_plan}\n\n"
                f"Leverage these insights to make an informed and strategic decision. "
                f"Remember to include the <TRADE_DECISION> JSON block at the end."
            ),
        }

        messages = [
            {"role": "system", "content": system_prompt},
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "trader_investment_plan": result.content,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
