from langchain_core.prompts import ChatPromptTemplate
from tradingagents.agents.utils.prompt_blocks import (
    ANTI_HALLUCINATION, STRICT_SYSTEM_PREAMBLE_NO_TOOLS
)
from tradingagents.dataflows.data_validator import DataValidator

def create_analyst_synthesizer(llm):
    def analyst_synthesizer_node(state):
        # Gather all available reports from the state
        reports = {
            "Market": state.get("market_report", ""),
            "Social Sentiment": state.get("sentiment_report", ""),
            "News": state.get("news_report", ""),
            "Fundamentals": state.get("fundamentals_report", ""),
            "Quant": state.get("quant_report", ""),
            "On-chain": state.get("onchain_report", ""),
            "Macro/Geo": state.get("macro_geo_report", ""),
            "Correlation": state.get("correlation_report", ""),
            "Prediction Market": state.get("prediction_market_report", ""),
        }
        
        # Filter out empty reports
        active_reports = {k: v for k, v in reports.items() if v}
        
        if not active_reports:
            return {
                "synthesizer_report": "No analyst reports available.",
                "data_quality_report": "FATAL: No data available to validate."
            }

        # Phase 16: Data Validation
        validator = DataValidator()
        trade_date = state.get("trade_date", "Unknown")
        ticker = state.get("company_of_interest", "")
        market_data = active_reports.get("Market", "")
        fund_data = active_reports.get("Fundamentals", "")
        
        quality_info = validator.get_overall_quality(market_data, fund_data, trade_date, ticker)
        quality_report = (
            f"Overall Data Quality Score: {quality_info['score']}\n"
            f"Price Data: {quality_info['price_quality']['report']}\n"
            f"Fundamentals Data: {quality_info['fundamentals_quality']['report']}\n"
            f"{quality_info['summary_warning']}"
        )
        
        # Inject quality info into reports text so Synthesizer sees it
        reports_text = f"**Data Quality Report (MUST CONSIDER)**:\n{quality_report}\n\n---\n\n"
        reports_text += "\n\n---\n\n".join(
            [f"**{name} Report**:\n{content}" for name, content in active_reports.items()]
        )
        
        system_message = (
            "You are the Lead Analyst Synthesizer. Your job is to read multiple independent analyst reports "
            "and create a single, unified executive briefing.\n\n"
            "Requirements:\n"
            "1. **Consensus**: Identify the major points of agreement across the different analyst domains.\n"
            "2. **Divergence**: Explicitly highlight any contradicting signals (e.g., strong technicals vs weak fundamentals).\n"
            "3. **Synthesis**: Provide a clear, objective summary of the overall situation.\n"
            "4. Do NOT make a final trade decision. You are setting the stage for the Bull vs Bear debate.\n\n"
            + ANTI_HALLUCINATION
        )
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", STRICT_SYSTEM_PREAMBLE_NO_TOOLS),
            ("human", "Here are the individual analyst reports:\n\n{reports_text}\n\nPlease synthesize them."),
        ])
        
        prompt = prompt.partial(
            system_message=system_message,
            current_date=state.get("trade_date", "Unknown"),
            ticker=state.get("company_of_interest", "Unknown")
        )
        
        response = llm.invoke(prompt.format_messages(reports_text=reports_text))
        
        return {
            "synthesizer_report": response.content,
            "data_quality_report": quality_report
        }
        
    return analyst_synthesizer_node
