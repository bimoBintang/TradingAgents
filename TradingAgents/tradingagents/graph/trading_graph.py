# TradingAgents/graph/trading_graph.py

import os
import json
import logging
from uuid import uuid4
from pathlib import Path
from datetime import date
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news,
)

# Phase 9: Advanced specialist tools
from tradingagents.agents.utils.advanced_tools import (
    get_options_chain,
    get_onchain_metrics,
    get_funding_rates,
    get_macro_indicators,
    get_peer_data,
)

# Phase 14: Polymarket prediction markets
from tradingagents.agents.utils.polymarket_tools import (
    get_prediction_markets,
    get_market_price,
)

# Phase 2: Portfolio and position tracking
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.position_tracker import PositionTracker
# Phase 3: Broker integration and execution
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.order_flow import OrderFlowAnalyzer
from tradingagents.execution.retry import RetryConfig
from tradingagents.execution.risk_controls import RiskController
from tradingagents.execution.stop_loss_manager import StopLossManager
from tradingagents.execution.brokers.broker_base import BaseBroker, BrokerConnectionError
# Phase 5: Persistent storage
from tradingagents.storage.database import Database
from tradingagents.storage.trade_journal import TradeJournal

from tradingagents.execution.brokers.paper_broker import PaperBroker

# Optional broker imports — only available when extra dependencies are installed
try:
    from tradingagents.execution.brokers.ccxt_broker import CcxtBroker
except ImportError:
    CcxtBroker = None  # type: ignore[assignment,misc]

try:
    from tradingagents.execution.brokers.alpaca_broker import AlpacaBroker
except ImportError:
    AlpacaBroker = None  # type: ignore[assignment,misc]

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


def _create_broker(config: Dict[str, Any], db=None) -> BaseBroker:
    """Factory function to create a broker based on configuration.

    Runs a health check after creation to verify connectivity.

    Args:
        config: Full configuration dictionary

    Returns:
        BaseBroker instance matching the configured broker type

    Raises:
        BrokerConnectionError: if broker fails health check
        ValueError: if broker_type is unknown
    """
    exec_cfg = config.get("execution", {})
    broker_type = exec_cfg.get("broker", "paper")
    portfolio_cfg = config.get("portfolio", {})

    broker: BaseBroker

    if broker_type == "paper":
        broker = PaperBroker(
            initial_cash=portfolio_cfg.get("initial_cash", 10000.0),
            commission_pct=exec_cfg.get("commission_pct", 0.001),
            slippage_pct=exec_cfg.get("slippage_pct", 0.0005),
        )

    elif broker_type == "ccxt":
        if CcxtBroker is None:
            raise ImportError(
                "Broker 'ccxt' dipilih tapi paket ccxt belum terinstall. "
                "Jalankan: pip install tradingagents[crypto]"
            )
        broker = CcxtBroker(
            exchange_id=exec_cfg.get("exchange", "bybit"),
            api_key=exec_cfg.get("api_key", ""),
            api_secret=exec_cfg.get("api_secret", ""),
            password=exec_cfg.get("password", ""),
            sandbox=exec_cfg.get("sandbox", True),
            default_quote_currency=exec_cfg.get("quote_currency", "USDT"),
            market_type=exec_cfg.get("market_type", "spot"),
            retry_config=RetryConfig.from_config(exec_cfg),
            db=db,
        )

    elif broker_type == "alpaca":
        if AlpacaBroker is None:
            raise ImportError(
                "Broker 'alpaca' dipilih tapi paket alpaca-py belum terinstall. "
                "Jalankan: pip install tradingagents[stocks]"
            )
        broker = AlpacaBroker(
            api_key=exec_cfg.get("api_key", ""),
            api_secret=exec_cfg.get("api_secret", ""),
            paper=exec_cfg.get("mode", "paper") != "live",
        )

    else:
        raise ValueError(f"Unknown broker type: {broker_type}. Use 'paper', 'ccxt', or 'alpaca'.")

    # Health check: ping broker to verify connectivity
    try:
        broker.health_check()
        logger.info("%s health check passed", broker.name)
    except Exception as e:
        logger.error("%s health check FAILED: %s", broker.name, e)
        raise

    return broker

class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework.
    
    Enhanced with:
    - Portfolio awareness (Phase 2): agents receive portfolio context
    - Broker integration (Phase 3): decisions can be auto-executed via brokers
    """

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals",
                           "quant", "onchain", "macro_geo", "correlation"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Phase 5: Session ID and storage
        self.session_id = str(uuid4())
        self.database = None
        self.journal = None
        storage_cfg = self.config.get("storage", {})
        if storage_cfg.get("enabled", False):
            try:
                self.database = Database(storage_cfg.get("db_path", "~/.tradingagents/trading.db"))
                self.journal = TradeJournal(
                    db=self.database,
                    session_id=self.session_id,
                    risk_free_rate_annual=storage_cfg.get("risk_free_rate_annual", 0.05),
                )
            except Exception as e:
                logger.warning("Database init failed: %s. Continuing without persistence.", e)
                self.database = None
                self.journal = None

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        # Initialize memories (Phase 5: with optional database persistence)
        mem_config = {"max_memory_items_per_agent": storage_cfg.get("max_memory_items_per_agent", 500)}
        self.bull_memory = FinancialSituationMemory("bull_memory", mem_config, self.config, database=self.database)
        self.bear_memory = FinancialSituationMemory("bear_memory", mem_config, self.config, database=self.database)
        self.trader_memory = FinancialSituationMemory("trader_memory", mem_config, self.config, database=self.database)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", mem_config, self.config, database=self.database)
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", mem_config, self.config, database=self.database)

        # ── Phase 2: Portfolio Manager ────────────────────────────────
        portfolio_cfg = self.config.get("portfolio", {})
        self.portfolio_manager = PortfolioManager(
            initial_cash=portfolio_cfg.get("initial_cash", 10000.0),
            max_position_pct=portfolio_cfg.get("max_position_pct", 0.1),
            max_total_positions=portfolio_cfg.get("max_total_positions", 10),
            state_file=portfolio_cfg.get("state_file"),
        )

        # ── Phase 2: Position Tracker ─────────────────────────────────
        tracker_cfg = self.config.get("position_tracker", {})
        self.position_tracker = PositionTracker(
            trailing_stop_pct=tracker_cfg.get("trailing_stop_pct", 0.0),
            max_hold_days=tracker_cfg.get("max_hold_days", 0),
        )

        # ── Phase 3: Broker & Execution Engine ────────────────────────
        exec_cfg = self.config.get("execution", {})
        self.execution_mode = exec_cfg.get("mode", "disabled")

        self.broker = None
        self.execution_engine = None

        if self.execution_mode != "disabled":
            self.broker = _create_broker(self.config, db=self.database)

            # Phase 4: Risk Controller (reads flat config keys)
            risk_cfg = self.config.get("risk_controls", {})
            if risk_cfg.get("kill_switch_enabled", True):
                self.risk_controller = RiskController(
                    max_drawdown_pct={
                        "daily": risk_cfg.get("max_daily_loss_pct", 0.05),
                        "weekly": risk_cfg.get("max_weekly_loss_pct", 0.10),
                    },
                    max_position_pct=risk_cfg.get("max_position_pct", 0.10),
                    max_concurrent_positions=risk_cfg.get("max_concurrent_positions", 5),
                    risk_per_trade_pct=risk_cfg.get("risk_per_trade_pct", 0.02),
                    consecutive_loss_limit=risk_cfg.get("consecutive_loss_limit", 3),
                    consecutive_loss_cooldown_seconds=risk_cfg.get("cooldown_seconds", 1800),
                    max_leverage=exec_cfg.get("max_leverage", 10),
                )
            else:
                self.risk_controller = None

            # Phase 4: StopLossManager (reads from risk_controls config)
            self.stop_loss_manager = StopLossManager(
                trailing_stop_pct=risk_cfg.get("trailing_stop_pct", 0.05),
                atr_multiplier=risk_cfg.get("atr_multiplier", 2.0),
                max_hold_hours=risk_cfg.get("max_hold_hours", 72),
            )

            # Phase 6: Notifier
            from tradingagents.notifications.notifier import Notifier
            self.notifier = Notifier(self.config)

            # Order Flow Analyzer
            order_flow_cfg = self.config.get("order_flow", {})
            if order_flow_cfg.get("enabled", False):
                self.order_flow_analyzer = OrderFlowAnalyzer(order_flow_cfg)
            else:
                self.order_flow_analyzer = None

            self.execution_engine = ExecutionEngine(
                broker=self.broker,
                portfolio_manager=self.portfolio_manager,
                position_tracker=self.position_tracker,
                risk_controller=self.risk_controller,
                stop_loss_manager=self.stop_loss_manager,
                journal=self.journal,
                notifier=self.notifier,
                order_flow_analyzer=self.order_flow_analyzer,
                min_confidence=exec_cfg.get("min_confidence", 0.5),
                max_daily_loss_pct=exec_cfg.get("max_daily_loss_pct", 0.05),
                cooldown_seconds=exec_cfg.get("cooldown_seconds", 300),
                require_confirmation=exec_cfg.get("require_confirmation", True),
                atr_timeframe=exec_cfg.get("atr_timeframe", "1h"),
                order_flow_config=order_flow_cfg,
            )

            # Phase 5b: Reconcile local portfolio with exchange on startup
            if exec_cfg.get("reconcile_on_startup", True):
                try:
                    report = self.execution_engine.reconcile()
                    logger.info("Startup reconciliation: %s", report.get("summary", ""))
                except Exception as e:
                    logger.warning("Startup reconciliation failed: %s", e)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.risk_manager_memory,
            self.conditional_logic,
            enable_execution_optimizer=self.config.get("enable_execution_optimizer", True),
        )

        self.propagator = Propagator()
        self.reflector = Reflector(
            self.quick_thinking_llm,
            database=self.database,
            session_id=self.session_id,
            max_reflections_loaded=storage_cfg.get("max_reflections_loaded", 20),
        )
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        return kwargs

    def _build_market_context(self) -> str:
        """Build dynamic market context string from config.

        Returns a system-level instruction block that agents MUST follow,
        ensuring prompts align with actual client config (spot vs futures).
        """
        exec_cfg = self.config.get("execution", {})
        market_type = exec_cfg.get("market_type", "spot")
        max_leverage = exec_cfg.get("max_leverage", 10)

        if market_type == "future":
            return (
                "⚙️ SYSTEM RULE — FUTURES MODE ACTIVE\n"
                f"You are trading on a FUTURES market (USDT-Margined Perpetual).\n"
                f"• Maximum allowed leverage: {max_leverage}x\n"
                "• You CAN open LONG or SHORT positions.\n"
                "• Choose leverage based on conviction: 1-3x (low), 5-10x (moderate), "
                f"10-{max_leverage}x (aggressive). Never exceed {max_leverage}x.\n"
                "• Default to 'isolated' margin. Use 'cross' only for hedged positions.\n"
                "• Higher leverage → smaller quantity_pct to manage risk.\n"
                "• Always consider funding rate and liquidation distance."
            )
        else:
            return (
                "⚙️ SYSTEM RULE — SPOT MODE ACTIVE\n"
                "You are trading on a SPOT market.\n"
                "• You MUST set leverage to 1 (no leverage allowed).\n"
                "• You MUST set position_side to 'LONG' (shorting not available on spot).\n"
                "• You MUST set margin_type to 'isolated'.\n"
                "• Do NOT attempt to short sell on spot markets."
            )

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
            # Phase 9: Advanced analyst tool nodes
            "quant": ToolNode(
                [
                    get_stock_data,
                    get_indicators,
                    get_options_chain,
                ]
            ),
            "onchain": ToolNode(
                [
                    get_onchain_metrics,
                    get_funding_rates,
                ]
            ),
            "macro_geo": ToolNode(
                [
                    get_global_news,
                    get_macro_indicators,
                ]
            ),
            "correlation": ToolNode(
                [
                    get_stock_data,
                    get_peer_data,
                ]
            ),
            # Phase 14: Polymarket prediction markets
            "prediction_market": ToolNode(
                [
                    get_prediction_markets,
                    get_market_price,
                ]
            ),
        }

    def propagate(self, company_name, trade_date, auto_execute: bool = False):
        """Run the trading agents graph for a company on a specific date.
        
        The graph includes portfolio state context so all agents can see
        current positions, cash balance, and trade history.
        
        Args:
            company_name: Ticker symbol or company name
            trade_date: Date string for the analysis
            auto_execute: If True and execution is enabled, auto-execute the decision
            
        Returns:
            Tuple of (final_state, processed_decision, order_result)
            - processed_decision is structured JSON string (or fallback text)
            - order_result is OrderResult if auto_execute=True and trade was placed, else None
        """
        self.ticker = company_name

        # Phase 2: Generate portfolio context for agent injection
        portfolio_context = self.portfolio_manager.get_portfolio_context_string()
        trade_history_context = self.portfolio_manager.get_trade_summary()

        # Generate dynamic market context from config
        market_context = self._build_market_context()

        # Initialize state with portfolio + market context
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            portfolio_context=portfolio_context,
            trade_history_context=trade_history_context,
            market_context=market_context,
        )
        args = self.propagator.get_graph_args()

        if self.debug:
            # Debug mode with tracing
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)

            final_state = trace[-1]
        else:
            # Standard mode without tracing
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection
        self.curr_state = final_state

        # Log state
        self._log_state(trade_date, final_state)

        # Process signal — returns structured JSON
        decision = self.signal_processor.process_signal(
            final_state["final_trade_decision"],
            ticker=self.ticker or "",
            execution_strategy=final_state.get("execution_strategy", ""),
        )

        # Phase 3: Auto-execute if enabled
        order_result = None
        if auto_execute and self.execution_engine and self.execution_mode != "disabled":
            order_result = self.execution_engine.execute_decision(decision)

        return final_state, decision, order_result

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "portfolio_state": final_state.get("portfolio_state", ""),
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file
        directory = Path(f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)

        with open(
            f"eval_results/{self.ticker}/TradingAgentsStrategy_logs/full_states_log_{trade_date}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(self.log_states_dict, f, indent=4)

    def reflect_and_remember(self, returns_losses):
        """Reflect on decisions and update memory based on returns."""
        self.reflector.reflect_bull_researcher(
            self.curr_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            self.curr_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            self.curr_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            self.curr_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            self.curr_state, returns_losses, self.risk_manager_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision.
        
        Returns a structured JSON string of TradeDecision when possible,
        with a fallback to simple BUY/SELL/HOLD text.
        """
        return self.signal_processor.process_signal(
            full_signal, ticker=self.ticker or ""
        )

    # ── Phase 2: Portfolio Access Methods ─────────────────────────────

    def get_portfolio_state(self):
        """Get the current portfolio state as a PortfolioState object."""
        return self.portfolio_manager.get_portfolio_state()

    def get_portfolio_summary(self) -> str:
        """Get a human-readable portfolio summary."""
        return self.portfolio_manager.get_portfolio_context_string()

    def get_trade_summary(self) -> str:
        """Get a summary of trading performance."""
        return self.portfolio_manager.get_trade_summary()

    def check_position_exits(self) -> list:
        """Check all positions for stop-loss, take-profit, or trailing stop triggers."""
        return self.position_tracker.check_all_exits(
            self.portfolio_manager.positions
        )

    # ── Phase 3: Execution Methods ────────────────────────────────────

    def execute_trade(
        self, decision_json: str, current_price: Optional[float] = None
    ) -> Optional["OrderResult"]:
        """Manually execute a trade decision via the configured broker.

        Args:
            decision_json: JSON string of a TradeDecision
            current_price: Current market price (fetched from broker if None)

        Returns:
            OrderResult if executed, None if skipped/rejected/disabled
        """
        if not self.execution_engine:
            logger.warning("Execution is disabled. Set execution.mode to 'paper' or 'live'.")
            return None
        return self.execution_engine.execute_decision(decision_json, current_price)

    def get_engine_status(self) -> dict:
        """Get the execution engine status."""
        if not self.execution_engine:
            return {"enabled": False, "mode": "disabled"}
        status = self.execution_engine.get_status()
        status["enabled"] = True
        status["mode"] = self.execution_mode
        return status

    def emergency_close_all(self) -> list:
        """Emergency: activate kill switch and close all positions."""
        if not self.execution_engine:
            logger.warning("Execution is disabled.")
            return []
        return self.execution_engine.emergency_close_all()
