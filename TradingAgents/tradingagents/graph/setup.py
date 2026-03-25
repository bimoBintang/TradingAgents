# TradingAgents/graph/setup.py

from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


# ── Helper: Build a single analyst subgraph (Analyst ↔ Tools → MsgClear) ──

def _build_analyst_subgraph(
    analyst_type: str,
    analyst_node,
    tool_node: ToolNode,
    conditional_logic: ConditionalLogic,
) -> StateGraph:
    """Build a self-contained analyst subgraph that handles its own tool loop.

    Each subgraph: START → Analyst ↔ tools → Msg Clear → END
    This allows multiple analysts to run in TRUE PARALLEL via fan-out.
    """
    sg = StateGraph(AgentState)

    # Sanitize node names for multi-word types like macro_geo
    display_name = analyst_type.replace("_", " ").title()
    analyst_label = f"{display_name} Analyst"
    tools_label = f"tools_{analyst_type}"
    clear_label = f"Msg Clear {display_name}"

    sg.add_node(analyst_label, analyst_node)
    sg.add_node(tools_label, tool_node)
    sg.add_node(clear_label, create_msg_delete())

    sg.add_edge(START, analyst_label)
    sg.add_conditional_edges(
        analyst_label,
        getattr(conditional_logic, f"should_continue_{analyst_type}"),
        [tools_label, clear_label],
    )
    sg.add_edge(tools_label, analyst_label)
    sg.add_edge(clear_label, END)

    return sg.compile()


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: ChatOpenAI,
        deep_thinking_llm: ChatOpenAI,
        tool_nodes: Dict[str, ToolNode],
        bull_memory,
        bear_memory,
        trader_memory,
        invest_judge_memory,
        risk_manager_memory,
        conditional_logic: ConditionalLogic,
        enable_execution_optimizer: bool = True,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.bull_memory = bull_memory
        self.bear_memory = bear_memory
        self.trader_memory = trader_memory
        self.invest_judge_memory = invest_judge_memory
        self.risk_manager_memory = risk_manager_memory
        self.conditional_logic = conditional_logic
        self.enable_execution_optimizer = enable_execution_optimizer

    def _get_llm_for_analyst(self, analyst_type: str):
        """Return the appropriate LLM for a given analyst type."""
        # Deep thinkers: complex reasoning tasks
        if analyst_type in ("macro_geo",):
            return self.deep_thinking_llm
        return self.quick_thinking_llm

    # ── Analyst Factory ───────────────────────────────────────────────

    ANALYST_FACTORIES = {
        "market": create_market_analyst,
        "social": create_social_media_analyst,
        "news": create_news_analyst,
        "fundamentals": create_fundamentals_analyst,
        "quant": create_quant_analyst,
        "onchain": create_onchain_analyst,
        "macro_geo": create_macro_geo_analyst,
        "correlation": create_correlation_analyst,
        "prediction_market": create_prediction_market_analyst,
    }

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph with PARALLEL analyst execution.

        Uses LangGraph fan-out/fan-in: all selected analysts run as parallel
        subgraphs, then their outputs are merged before the Researcher Debate.

        Args:
            selected_analysts (list): List of analyst types to include.
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # ── Step 1: Build parallel analyst subgraphs ──────────────────

        analyst_subgraphs = {}
        for analyst_type in selected_analysts:
            factory = self.ANALYST_FACTORIES.get(analyst_type)
            if not factory:
                raise ValueError(f"Unknown analyst type: {analyst_type}")

            if analyst_type not in self.tool_nodes:
                raise ValueError(f"No tool node configured for analyst: {analyst_type}")

            llm = self._get_llm_for_analyst(analyst_type)
            analyst_node = factory(llm)
            tool_node = self.tool_nodes[analyst_type]

            subgraph = _build_analyst_subgraph(
                analyst_type, analyst_node, tool_node, self.conditional_logic
            )
            analyst_subgraphs[analyst_type] = subgraph

        # ── Step 2: Create researcher, trader, risk nodes ─────────────

        bull_researcher_node = create_bull_researcher(
            self.quick_thinking_llm, self.bull_memory
        )
        bear_researcher_node = create_bear_researcher(
            self.quick_thinking_llm, self.bear_memory
        )
        research_manager_node = create_research_manager(
            self.deep_thinking_llm, self.invest_judge_memory
        )
        trader_node = create_trader(self.quick_thinking_llm, self.trader_memory)

        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        risk_manager_node = create_risk_manager(
            self.deep_thinking_llm, self.risk_manager_memory
        )

        # ── Step 3: Build the main workflow ───────────────────────────

        workflow = StateGraph(AgentState)

        # Add each analyst subgraph as a node (they execute internally)
        for analyst_type, subgraph in analyst_subgraphs.items():
            display_name = analyst_type.replace("_", " ").title()
            workflow.add_node(f"{display_name} Analyst", subgraph)

        # Add post-analysis nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Risk Judge", risk_manager_node)

        # ── Step 4: Fan-out → all analysts in parallel ────────────────

        analyst_display_names = [
            f"{at.replace('_', ' ').title()} Analyst"
            for at in selected_analysts
        ]

        # START fans out to ALL analysts simultaneously
        for name in analyst_display_names:
            workflow.add_edge(START, name)

        # All analysts fan-in to Bull Researcher
        for name in analyst_display_names:
            workflow.add_edge(name, "Bull Researcher")

        # ── Step 5: Researcher debate → Trader → Risk ─────────────────

        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")

        # Execution Optimizer (between Trader and Risk team)
        if self.enable_execution_optimizer:
            execution_optimizer_node = create_execution_optimizer(self.deep_thinking_llm)
            workflow.add_node("Execution Optimizer", execution_optimizer_node)
            workflow.add_edge("Trader", "Execution Optimizer")
            workflow.add_edge("Execution Optimizer", "Aggressive Analyst")
        else:
            workflow.add_edge("Trader", "Aggressive Analyst")

        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Risk Judge": "Risk Judge",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Risk Judge": "Risk Judge",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Risk Judge": "Risk Judge",
            },
        )

        workflow.add_edge("Risk Judge", END)

        # Compile and return
        return workflow.compile()
