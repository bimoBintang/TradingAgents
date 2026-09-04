"""Prediction Market Analyst — extracts forward-looking probability signals
from Polymarket prediction markets.

This is the 9th analyst agent in the TradingAgents pipeline.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.polymarket_tools import (
    get_prediction_markets,
    get_market_price,
)
from tradingagents.agents.utils.prompt_blocks import terse_suffix


def create_prediction_market_analyst(llm):
    """Create a Prediction Market Analyst node for the LangGraph pipeline.

    Searches Polymarket for events relevant to the ticker being analyzed,
    extracts YES/NO probabilities, and translates them into trading signals.
    """

    def prediction_market_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        tools = [
            get_prediction_markets,
            get_market_price,
        ]

        system_message = (
            "You are a Prediction Markets analyst specializing in extracting "
            "forward-looking probability signals from Polymarket (a decentralized "
            "prediction market where real money is wagered on future outcomes).\n\n"
            "YOUR TASK:\n"
            "1. Use get_prediction_markets(query) to search for active events "
            "related to the company, sector, or macro conditions.\n"
            "   - For stocks (e.g. NVDA, TSLA): search the company name, sector, "
            "and related regulatory/geopolitical topics.\n"
            "   - For crypto (e.g. BTC-USD, ETH-USD): search 'bitcoin', 'ethereum', "
            "'SEC', 'ETF', 'regulation', 'fed rate'.\n"
            "2. Identify the 3-5 MOST RELEVANT markets and report their YES/NO "
            "probabilities.\n"
            "3. Translate probabilities into trading implications:\n"
            "   - If 'Fed cuts rates in June' = 72% YES → bullish for equities\n"
            "   - If 'SEC approves ETH ETF' = 85% YES → bullish for ETH\n"
            "   - If 'US recession by Q4' = 45% YES → cautious macro outlook\n"
            "   - If 'Trump wins election' = 60% YES → analyze policy implications\n"
            "4. Provide a SUMMARY TABLE with columns: Event | Probability | "
            "Trading Implication\n\n"
            "CRITICAL RULES:\n"
            "- DO NOT hallucinate probabilities. ONLY cite numbers returned by tools.\n"
            "- If no relevant markets are found, say so honestly.\n"
            "- Focus on markets with high volume/liquidity (stronger signal).\n"
            "- Explain the CAUSAL CHAIN: why does this probability affect the ticker?\n"
            "- These are 'Wisdom of the Crowd' signals backed by real money — "
            "they often lead traditional news by hours or days."
            + terse_suffix()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. We are looking at the company {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "prediction_market_report": report,
        }

    return prediction_market_analyst_node
