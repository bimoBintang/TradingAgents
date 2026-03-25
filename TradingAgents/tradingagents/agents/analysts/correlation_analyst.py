from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import get_stock_data
from tradingagents.agents.utils.advanced_tools import get_peer_data


def create_correlation_analyst(llm):
    """Create a Correlation & Cross-Asset Analyst node for the LangGraph pipeline.

    Discovers hidden relationships between the target asset and its peers,
    sector ETFs, and benchmark indices.
    """

    def correlation_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        tools = [get_stock_data, get_peer_data]

        # Determine sensible peer group based on ticker pattern
        ticker_upper = ticker.upper()
        if any(c in ticker_upper for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"]):
            default_peers = "BTC-USD,ETH-USD,SOL-USD,^GSPC"
        else:
            default_peers = "SPY,QQQ,^GSPC,^VIX"

        system_message = (
            "You are a Cross-Asset Correlation Analyst specializing in finding hidden "
            "relationships between financial instruments. Your task is to analyze how "
            "the target asset relates to its peers and benchmarks. Produce a report covering:\n\n"
            f"Suggested peer group for {ticker}: {default_peers}\n\n"
            "1. **Correlation Analysis**: Calculate and interpret the rolling correlation "
            "between the target and each peer. High correlation = move together. "
            "Low/negative = potential diversification or decoupling.\n"
            "2. **Beta Calculation**: The asset's beta vs the benchmark. "
            "Beta > 1 = more volatile than market. Beta < 1 = more defensive.\n"
            "3. **Relative Strength**: Is the target outperforming or underperforming its peers? "
            "Persistent outperformance = momentum signal.\n"
            "4. **Sector Rotation Clues**: Based on peer performance, is money flowing toward "
            "or away from this asset class/sector?\n"
            "5. **Lead-Lag Observations**: Note if any peer tends to move before the target "
            "(predictive signal).\n"
            "6. **Cross-Asset Verdict**: Clear conclusion on what the cross-asset landscape "
            "implies for the target asset direction.\n\n"
            "Append a Markdown correlation matrix table at the end."
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
            "correlation_report": report,
        }

    return correlation_analyst_node
