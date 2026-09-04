from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import get_global_news
from tradingagents.agents.utils.advanced_tools import get_macro_indicators
from tradingagents.agents.utils.prompt_blocks import terse_suffix


def create_macro_geo_analyst(llm):
    """Create a Macro-Geopolitics Analyst node for the LangGraph pipeline.

    Analyzes macroeconomic regimes, central bank policy, currency strength,
    geopolitical risks, and their impact on the target asset.
    Uses deep_think_llm for complex reasoning.
    """

    def macro_geo_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]

        tools = [get_global_news, get_macro_indicators]

        system_message = (
            "You are a senior Macro-Geopolitics Strategist at a global investment bank. "
            "Your role is to assess the macroeconomic and geopolitical landscape and how it "
            "impacts the asset under analysis. Produce a report covering:\n\n"
            "1. **Interest Rate Regime**: Fed Funds rate trajectory, yield curve shape "
            "(inverted = recession risk). Impact on risk assets.\n"
            "2. **Dollar Strength (DXY)**: Is the dollar strengthening or weakening? "
            "A strong dollar typically pressures commodities and crypto.\n"
            "3. **Fear Gauge (VIX)**: Current VIX level and trend. VIX > 25 = elevated fear. "
            "VIX < 15 = complacency.\n"
            "4. **Commodity Signals**: Gold, Oil trends as leading macro indicators. "
            "Rising gold = flight to safety. Rising oil = inflationary pressure.\n"
            "5. **Equity Market Context**: S&P 500 trend as a risk-on/risk-off barometer.\n"
            "6. **Geopolitical Risk Assessment**: Based on global news, assess any geopolitical "
            "events (wars, sanctions, elections, regulatory changes) that could cause volatility.\n"
            "7. **Macro Verdict**: Clear conclusion on whether the macro environment is "
            "favorable, neutral, or hostile for the target asset.\n\n"
            "Append a Markdown table at the end with all macro indicators and their signals."
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
            "macro_geo_report": report,
        }

    return macro_geo_analyst_node
