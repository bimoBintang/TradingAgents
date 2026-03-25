# TradingAgents/graph/reflection.py

"""Reflection module for learning from past trading decisions.

Phase 5: Added optional database persistence for reflections.
Previous session learnings are loaded from DB and injected into reflection prompts.
"""

from typing import Dict, Any, Optional, List
from langchain_openai import ChatOpenAI


class Reflector:
    """Handles reflection on decisions and updating memory.

    With optional database persistence:
    - Saves reflections to SQLite after each generation
    - Loads previous session learnings for context injection
    """

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        database=None,
        session_id: Optional[str] = None,
        max_reflections_loaded: int = 20,
    ):
        """Initialize the reflector with an LLM.

        Args:
            quick_thinking_llm: LLM for generating reflections
            database: Optional Database instance for persistence
            session_id: Current session identifier
            max_reflections_loaded: Max previous reflections to load per ticker
        """
        self.quick_thinking_llm = quick_thinking_llm
        self.db = database
        self.session_id = session_id
        self.max_reflections_loaded = max_reflections_loaded
        self.reflection_system_prompt = self._get_reflection_prompt()

    def _get_reflection_prompt(self) -> str:
        """Get the system prompt for reflection."""
        return """
You are an expert financial analyst tasked with reviewing trading decisions/analysis and providing a comprehensive, step-by-step analysis. 
Your goal is to deliver detailed insights into investment decisions and highlight opportunities for improvement, adhering strictly to the following guidelines:

1. Reasoning:
   - For each trading decision, determine whether it was correct or incorrect. A correct decision results in an increase in returns, while an incorrect decision does the opposite.
   - Analyze the contributing factors to each success or mistake. Consider:
     - Market intelligence.
     - Technical indicators.
     - Technical signals.
     - Price movement analysis.
     - Overall market data analysis 
     - News analysis.
     - Social media and sentiment analysis.
     - Fundamental data analysis.
     - Weight the importance of each factor in the decision-making process.

2. Improvement:
   - For any incorrect decisions, propose revisions to maximize returns.
   - Provide a detailed list of corrective actions or improvements, including specific recommendations (e.g., changing a decision from HOLD to BUY on a particular date).

3. Summary:
   - Summarize the lessons learned from the successes and mistakes.
   - Highlight how these lessons can be adapted for future trading scenarios and draw connections between similar situations to apply the knowledge gained.

4. Query:
   - Extract key insights from the summary into a concise sentence of no more than 1000 tokens.
   - Ensure the condensed sentence captures the essence of the lessons and reasoning for easy reference.

Adhere strictly to these instructions, and ensure your output is detailed, accurate, and actionable. You will also be given objective descriptions of the market from a price movements, technical indicator, news, and sentiment perspective to provide more context for your analysis.
"""

    def _get_previous_learnings(self, ticker: Optional[str] = None) -> str:
        """Load previous session reflections from database.

        Args:
            ticker: Optional ticker to filter reflections

        Returns:
            Formatted string of previous learnings, or empty string
        """
        if not self.db:
            return ""

        try:
            reflections = self.db.query_reflections(
                ticker=ticker,
                limit=self.max_reflections_loaded,
            )

            if not reflections:
                return ""

            lines = ["=== Previous session learnings ==="]
            for r in reflections:
                agent = r.get("agent_name", "unknown")
                date = r.get("created_at", "")[:10]
                content = r.get("content", "")
                lines.append(f"[{agent} | {date}]\n{content}")
                lines.append("---")

            return "\n".join(lines)

        except Exception:
            return ""

    def _extract_current_situation(self, current_state: Dict[str, Any]) -> str:
        """Extract the current market situation from the state."""
        curr_market_report = current_state["market_report"]
        curr_sentiment_report = current_state["sentiment_report"]
        curr_news_report = current_state["news_report"]
        curr_fundamentals_report = current_state["fundamentals_report"]

        return f"{curr_market_report}\n\n{curr_sentiment_report}\n\n{curr_news_report}\n\n{curr_fundamentals_report}"

    def _extract_ticker(self, current_state: Dict[str, Any]) -> Optional[str]:
        """Try to extract ticker from state."""
        return current_state.get("ticker")

    def _reflect_on_component(
        self, component_type: str, report: str, situation: str, returns_losses,
        ticker: Optional[str] = None,
    ) -> str:
        """Generate reflection for a component.

        Injects previous learnings from database if available.
        """
        # Load previous learnings for context
        previous = self._get_previous_learnings(ticker)

        context_parts = [
            f"Returns: {returns_losses}",
            f"\n\nAnalysis/Decision: {report}",
            f"\n\nObjective Market Reports for Reference: {situation}",
        ]

        if previous:
            context_parts.append(f"\n\n{previous}")

        messages = [
            ("system", self.reflection_system_prompt),
            ("human", "".join(context_parts)),
        ]

        result = self.quick_thinking_llm.invoke(messages).content

        # Persist reflection to database
        if self.db:
            try:
                self.db.insert_reflection(
                    agent_name=component_type.lower(),
                    ticker=ticker,
                    session_id=self.session_id,
                    content=result,
                )
            except Exception:
                pass  # Never interrupt for logging failures

        return result

    def reflect_bull_researcher(self, current_state, returns_losses, bull_memory):
        """Reflect on bull researcher's analysis and update memory."""
        situation = self._extract_current_situation(current_state)
        ticker = self._extract_ticker(current_state)
        bull_debate_history = current_state["investment_debate_state"]["bull_history"]

        result = self._reflect_on_component(
            "BULL", bull_debate_history, situation, returns_losses, ticker
        )
        bull_memory.add_situations([(situation, result)])

    def reflect_bear_researcher(self, current_state, returns_losses, bear_memory):
        """Reflect on bear researcher's analysis and update memory."""
        situation = self._extract_current_situation(current_state)
        ticker = self._extract_ticker(current_state)
        bear_debate_history = current_state["investment_debate_state"]["bear_history"]

        result = self._reflect_on_component(
            "BEAR", bear_debate_history, situation, returns_losses, ticker
        )
        bear_memory.add_situations([(situation, result)])

    def reflect_trader(self, current_state, returns_losses, trader_memory):
        """Reflect on trader's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        ticker = self._extract_ticker(current_state)
        trader_decision = current_state["trader_investment_plan"]

        result = self._reflect_on_component(
            "TRADER", trader_decision, situation, returns_losses, ticker
        )
        trader_memory.add_situations([(situation, result)])

    def reflect_invest_judge(self, current_state, returns_losses, invest_judge_memory):
        """Reflect on investment judge's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        ticker = self._extract_ticker(current_state)
        judge_decision = current_state["investment_debate_state"]["judge_decision"]

        result = self._reflect_on_component(
            "INVEST JUDGE", judge_decision, situation, returns_losses, ticker
        )
        invest_judge_memory.add_situations([(situation, result)])

    def reflect_risk_manager(self, current_state, returns_losses, risk_manager_memory):
        """Reflect on risk manager's decision and update memory."""
        situation = self._extract_current_situation(current_state)
        ticker = self._extract_ticker(current_state)
        judge_decision = current_state["risk_debate_state"]["judge_decision"]

        result = self._reflect_on_component(
            "RISK JUDGE", judge_decision, situation, returns_losses, ticker
        )
        risk_manager_memory.add_situations([(situation, result)])
