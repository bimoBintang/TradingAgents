import json
from tradingagents.agents.utils.prompt_blocks import (
    ANTI_HALLUCINATION, CONFIDENCE_SCORING, STRICT_SYSTEM_PREAMBLE_NO_TOOLS,
)


RISK_MANAGER_PROMPT = """As the Risk Management Judge and Debate Facilitator, evaluate the debate between three risk analysts—Aggressive, Neutral, and Conservative—and determine the best course of action.

{portfolio_context}

Your decision must be clear and actionable. After your analysis, you MUST end your response with a structured JSON block wrapped in <RISK_ASSESSMENT> tags:

<RISK_ASSESSMENT>
{{
    "approved": true | false,
    "original_action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
    "adjusted_action": "BUY" | "SELL" | "HOLD" | "STRONG_BUY" | "STRONG_SELL",
    "adjusted_quantity_pct": <float 0.0 to 1.0>,
    "risk_score": <float 0.0 to 1.0>,
    "max_acceptable_loss": <float in currency or null>,
    "adjusted_stop_loss_pct": <float or null>,
    "adjusted_take_profit_pct": <float or null>,
    "risk_factors": ["<risk1>", "<risk2>", ...],
    "mitigation_notes": "<risk mitigation strategy>",
    "reasoning": "<detailed reasoning>"
}}
</RISK_ASSESSMENT>

Guidelines:
1. **Summarize Key Arguments**: Extract the strongest points from each analyst.
2. **Provide Rationale**: Support your recommendation with direct quotes and counterarguments.
3. **Refine the Trader's Plan**: Start with the trader's plan and adjust based on risk insights.
4. **Learn from Past Mistakes**: Use past reflections to avoid repeating errors.
5. **Risk Adjustments**:
   - If volatility is high, reduce quantity_pct by 30-50%
   - If conflicting signals exist, tighten stop_loss_pct
   - If portfolio is already exposed, consider reducing or rejecting
   - Set approved=false only for genuinely dangerous trades (risk_score > 0.8)

Risk Score Guidelines:
- 0.0-0.3: Low risk — approve as-is
- 0.3-0.5: Moderate risk — approve with minor adjustments
- 0.5-0.7: Elevated risk — approve with significant adjustments
- 0.7-0.8: High risk — approve only with major reductions
- 0.8-1.0: Very high risk — consider rejection

IMPORTANT: Always end with the <RISK_ASSESSMENT> JSON block.

""" + ANTI_HALLUCINATION + """

""" + CONFIDENCE_SCORING


def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:
        company_name = state["company_of_interest"]
        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["investment_plan"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        # Build portfolio context
        portfolio_context = ""
        portfolio_state = state.get("portfolio_state")
        if portfolio_state:
            portfolio_context = portfolio_state
        else:
            portfolio_context = "No portfolio information available."

        prompt = RISK_MANAGER_PROMPT.format(
            portfolio_context=portfolio_context,
        ) + f"""

Trader's Original Plan:
{trader_plan}

Past Lessons Learned:
{past_memory_str if past_memory_str else "No past lessons available."}

---

**Analysts Debate History:**
{history}

---

Focus on actionable insights and continuous improvement. Build on past lessons, critically evaluate all perspectives, and ensure each decision advances better outcomes. Remember to include the <RISK_ASSESSMENT> JSON block at the end."""

        response = llm.invoke(prompt)

        new_risk_debate_state = {
            "judge_decision": response.content,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response.content,
        }

    return risk_manager_node
