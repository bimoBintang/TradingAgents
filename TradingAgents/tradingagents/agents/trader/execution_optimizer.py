import functools


EXECUTION_OPTIMIZER_PROMPT = """You are an elite Execution Strategy Optimizer at a quantitative trading firm.

You receive a trade decision from the Trader Agent and your job is to optimize HOW to execute it,
not WHAT to trade. The Trader has already decided the direction and size.

Current Portfolio Context:
{portfolio_context}

Your analysis MUST cover:

1. **Entry Timing**: Based on volume profiles and market microstructure, suggest the optimal
   window to enter (e.g., avoid first 15min of market open, target VWAP zones, London/NY overlap for crypto).

2. **Order Type Optimization**: Should this be a market order (for urgency/momentum) or a limit order
   (for better fill at key support/resistance levels)? Justify your choice.

3. **Position Laddering (DCA)**: If confidence is moderate (0.5–0.7), suggest splitting the entry
   into 2–3 tranches at specific price levels instead of going all-in.

4. **Slippage Mitigation**: For larger orders, suggest TWAP (Time-Weighted) or VWAP
   (Volume-Weighted) execution to minimize market impact.

5. **Exit Strategy Refinement**: Review the Trader's stop-loss and take-profit levels.
   Suggest volatility-adjusted levels using ATR (Average True Range) if the original levels
   seem too tight or too wide.

6. **Risk-Adjusted Position Size**: Verify that the position size respects the portfolio's
   risk parameters (max position %, current exposure, drawdown headroom).

After your analysis, output the ENHANCED execution plan by wrapping it in <EXECUTION_STRATEGY> tags:

<EXECUTION_STRATEGY>
{{
    "entry_timing": "<optimal entry window description>",
    "order_type": "MARKET" | "LIMIT",
    "limit_price": <float or null>,
    "ladder_entries": [
        {{"price": <float>, "pct_of_total": <float>}},
    ],
    "execution_method": "SINGLE" | "TWAP" | "VWAP" | "DCA",
    "refined_stop_loss_pct": <float>,
    "refined_take_profit_pct": <float>,
    "atr_based_stop": <float or null>,
    "max_slippage_tolerance_pct": <float>,
    "urgency": "LOW" | "MEDIUM" | "HIGH",
    "notes": "<any additional tactical notes>"
}}
</EXECUTION_STRATEGY>

IMPORTANT: Always output the <EXECUTION_STRATEGY> JSON block. The JSON must be valid."""


def create_execution_optimizer(llm):
    """Create an Execution Strategy Optimizer node.

    Sits between Trader and Risk Management. Enhances the trade execution plan
    with optimal timing, order splitting, and volatility-adjusted levels.
    """

    def execution_optimizer_node(state, name):
        trader_plan = state.get("trader_investment_plan", "No trader plan available.")

        portfolio_context = state.get("portfolio_state", "No portfolio information available.")
        market_report = state.get("market_report", "")
        quant_report = state.get("quant_report", "")

        system_prompt = EXECUTION_OPTIMIZER_PROMPT.format(
            portfolio_context=portfolio_context,
        )

        context = {
            "role": "user",
            "content": (
                f"The Trader Agent has produced the following trade plan:\n\n"
                f"{trader_plan}\n\n"
                f"Market Report Summary:\n{market_report[:500]}\n\n"
                f"Quant Report Summary:\n{quant_report[:500]}\n\n"
                f"Based on this, optimize the execution strategy. "
                f"Include the <EXECUTION_STRATEGY> JSON block at the end."
            ),
        }

        messages = [
            {"role": "system", "content": system_prompt},
            context,
        ]

        result = llm.invoke(messages)

        return {
            "messages": [result],
            "execution_strategy": result.content,
            "sender": name,
        }

    return functools.partial(execution_optimizer_node, name="Execution Optimizer")
