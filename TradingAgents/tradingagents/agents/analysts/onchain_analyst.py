from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.advanced_tools import get_onchain_metrics, get_funding_rates
from tradingagents.agents.utils.prompt_blocks import terse_suffix


def create_onchain_analyst(llm):
    """Create an On-Chain / DeFi Analyst node for the LangGraph pipeline.

    Specializes in blockchain-native intelligence: whale activity,
    exchange flows, network health, DeFi TVL, and funding rates.
    Only activated for crypto tickers.
    """

    def onchain_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        tools = [get_onchain_metrics, get_funding_rates]

        system_message = (
            "You are an expert On-Chain and DeFi Intelligence Analyst. "
            "Your task is to analyze blockchain-native metrics for crypto assets. "
            "Produce a comprehensive on-chain report covering:\n\n"
            "1. **Market Overview**: Current price, market cap, volume, supply metrics.\n"
            "2. **Supply Dynamics**: Circulating vs max supply ratio and what it implies "
            "for inflation/scarcity.\n"
            "3. **Momentum Signals**: 24h/7d/30d price change momentum analysis.\n"
            "4. **Distance from ATH**: How far the asset is from its all-time high "
            "and what this implies for upside potential.\n"
            "5. **Funding Rate Analysis**: Current perpetual futures funding rate. "
            "Positive rates = bullish crowding (potential for long squeeze). "
            "Negative rates = bearish crowding (potential for short squeeze).\n"
            "6. **Community Sentiment**: Voting/sentiment data if available.\n"
            "7. **On-Chain Verdict**: Clear conclusion on whether on-chain signals "
            "are bullish, bearish, or neutral.\n\n"
            "Append a Markdown table at the end summarizing the key on-chain metrics."
            + terse_suffix()
        )

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "You are a helpful AI assistant, collaborating with other assistants."
                " Use the provided tools to progress towards answering the question."
                " If you are unable to fully answer, that's OK; another assistant with different tools"
                " will help where you left off. Execute what you can to make progress."
                " You have access to the following tools: {tool_names}.\n{system_message}"
                " For your reference, the current date is {current_date}. The ticker is {ticker}.",
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
            "onchain_report": report,
        }

    return onchain_analyst_node
