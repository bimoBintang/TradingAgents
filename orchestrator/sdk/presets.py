"""
Presets — Ready-to-use orchestrator templates for common trading workflows.

Provides factory functions that wire together a pre-built orchestration
topology tailored for crypto trading use cases.

Usage:
    from orchestrator.sdk.presets import create_trading_orchestrator

    orch = create_trading_orchestrator(
        ticker="BTCUSDT",
        topology="pipeline",
        allowed_tickers={"BTCUSDT", "ETHUSDT"},
        budget_usd=0.50,
    )
    result = orch.run_sync()
"""

import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


def create_trading_orchestrator(
    ticker: str,
    topology: str = "pipeline",
    session_id: Optional[str] = None,
    allowed_tickers: Optional[Set[str]] = None,
    budget_usd: float = 1.00,
    failure_threshold: int = 3,
    drawdown_limit: float = -0.15,
):
    """
    Create a fully-configured Orchestrator with all safety layers attached.

    Pre-wired components:
      - TopologyRouter (configurable topology)
      - GuardRails (allowed tickers, confidence validation)
      - TokenMeter (session budget enforcement)
      - CircuitBreaker (per-agent + drawdown protection)
      - LongTermMemory (cross-session trade memory)
      - ReasoningBank (pattern-based suggestions)

    Args:
        ticker:           Trading pair, e.g. "BTCUSDT"
        topology:         "pipeline" | "hierarchical" | "mesh"
        session_id:       Optional custom session ID
        allowed_tickers:  Set of valid ticker symbols (None = allow all)
        budget_usd:       Max LLM API spend per session
        failure_threshold Agent circuit opens after this many failures
        drawdown_limit:   Kill trading if drawdown exceeds this (e.g. -0.15)

    Returns:
        A configured TradingOrchestrator instance with all layers active.
    """
    from orchestrator.orchestrator import Orchestrator
    from orchestrator.core import Topology
    from orchestrator.guards import GuardRails, TokenMeter, CircuitBreaker
    from orchestrator.memory import LongTermMemory, ReasoningBank

    topo_map = {
        "pipeline": Topology.PIPELINE,
        "hierarchical": Topology.HIERARCHICAL,
        "mesh": Topology.MESH,
    }
    topo = topo_map.get(topology.lower(), Topology.PIPELINE)
    tickers = allowed_tickers or {ticker}

    orch = Orchestrator(ticker=ticker, topology=topo, session_id=session_id)

    # Attach safety layers as attributes for agent access
    orch.guard   = GuardRails(allowed_tickers=tickers)
    orch.meter   = TokenMeter(session_id=orch.session_id, session_budget_usd=budget_usd)
    orch.breaker = CircuitBreaker(failure_threshold=failure_threshold)
    orch.ltm     = LongTermMemory()
    orch.rb      = ReasoningBank()

    # Store configuration
    orch._drawdown_limit = drawdown_limit

    logger.info(
        "[Preset] TradingOrchestrator created | ticker=%s | topology=%s | budget=$%.2f",
        ticker, topology, budget_usd,
    )
    return orch
