"""
Orchestrator — Main entry point for the CMAOP platform.

Ties together AgentBus, TopologyRouter, StateManager, and ToolRegistry
into a single cohesive runtime.
"""

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from .core import AgentBus, StateManager, TopologyRouter, Topology, ToolRegistry
from .core.topology_router import RunResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    High-level facade for the Custom Multi-Agent Orchestration Platform.

    Usage:
        orch = Orchestrator(ticker="BTCUSDT", topology=Topology.PIPELINE)

        @orch.agent(role="Quant Analyst", priority=10)
        async def quant_agent(state, bus, **kwargs):
            report = run_quant_analysis(state.ticker)
            state.set("analysis", "quant_report", report, writer="quant")
            return report

        result = await orch.run()
        print(result.final_decision)
    """

    def __init__(
        self,
        ticker: str,
        topology: Topology = Topology.PIPELINE,
        session_id: Optional[str] = None,
        max_concurrent: int = 5,
    ):
        self.ticker = ticker
        self.session_id = session_id or str(uuid.uuid4())[:10]
        self.topology = topology

        # Core components
        self.bus = AgentBus(session_id=self.session_id)
        self.state = StateManager(ticker=ticker, session_id=self.session_id)
        self.router = TopologyRouter(topology=topology, max_concurrent=max_concurrent)
        self.tools = ToolRegistry()

        logger.info(
            "[Orchestrator] Initialized | ticker=%s | topology=%s | session=%s",
            ticker, topology.value, self.session_id,
        )

    # ── Agent Registration Decorator ──────────────────────────────────

    def agent(
        self,
        role: str,
        agent_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        priority: int = 50,
        timeout: float = 120.0,
    ):
        """Decorator to register a function as an agent in this orchestrator."""
        def decorator(fn: Callable) -> Callable:
            _agent_id = agent_id or fn.__name__
            self.router.add_agent(
                agent_id=_agent_id,
                role=role,
                handler=fn,
                depends_on=depends_on or [],
                priority=priority,
                timeout=timeout,
            )
            self.bus.register_agent(_agent_id, role)
            return fn
        return decorator

    # ── Tool Registration ─────────────────────────────────────────────

    def tool(
        self,
        name: Optional[str] = None,
        description: str = "",
        category: str = "general",
    ):
        """Decorator to register a function as a tool in this orchestrator."""
        return self.tools.tool(name=name, description=description, category=category)

    # ── Execution ─────────────────────────────────────────────────────

    async def run(self, **kwargs) -> "OrchestrationResult":
        """Execute the full orchestration and return a result summary."""
        logger.info(
            "[Orchestrator] Running %s analysis for %s (%s topology)",
            self.ticker, self.session_id, self.topology.value,
        )

        results: List[RunResult] = await self.router.run(
            state=self.state,
            bus=self.bus,
            tools=self.tools,
            **kwargs,
        )

        # Publish completion event
        from .core.agent_bus import Message
        await self.bus.publish(Message(
            topic="orchestrator.completed",
            sender="orchestrator",
            payload={
                "session_id": self.session_id,
                "ticker": self.ticker,
                "agents_run": len(results),
                "successful": sum(1 for r in results if r.success),
            },
            session_id=self.session_id,
        ))

        return OrchestrationResult(
            session_id=self.session_id,
            ticker=self.ticker,
            topology=self.topology.value,
            run_results=results,
            state_snapshot=self.state.snapshot(),
        )

    def run_sync(self, **kwargs) -> "OrchestrationResult":
        """Synchronous wrapper around run()."""
        return asyncio.run(self.run(**kwargs))

    # ── Inspection ────────────────────────────────────────────────────

    def describe(self) -> dict:
        """Return a description of this orchestrator's configuration."""
        return {
            "session_id": self.session_id,
            "ticker": self.ticker,
            "topology": self.topology.value,
            "agents": self.router.summary(),
            "tools": self.tools.summary(),
            "execution_plan": self.router.get_execution_plan(),
        }


class OrchestrationResult:
    """Result container returned after a full orchestration run."""

    def __init__(
        self,
        session_id: str,
        ticker: str,
        topology: str,
        run_results: List[RunResult],
        state_snapshot,
    ):
        self.session_id = session_id
        self.ticker = ticker
        self.topology = topology
        self.run_results = run_results
        self.state_snapshot = state_snapshot

    @property
    def final_decision(self) -> Optional[Dict[str, Any]]:
        """Return the final trade decision from the state, if any."""
        return self.state_snapshot.decisions[-1] if self.state_snapshot.decisions else None

    @property
    def success_rate(self) -> float:
        """Fraction of agents that completed successfully."""
        if not self.run_results:
            return 0.0
        return sum(1 for r in self.run_results if r.success) / len(self.run_results)

    @property
    def total_duration(self) -> float:
        """Total wall-clock time of all agent runs (sum, not parallel time)."""
        return sum(r.duration_seconds for r in self.run_results)

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "ticker": self.ticker,
            "topology": self.topology,
            "agents_run": len(self.run_results),
            "success_rate": f"{self.success_rate:.1%}",
            "total_agent_time": f"{self.total_duration:.2f}s",
            "final_decision": self.final_decision,
            "failed_agents": [r.agent_id for r in self.run_results if not r.success],
        }

    def __repr__(self) -> str:
        return (
            f"<OrchestrationResult ticker={self.ticker} "
            f"agents={len(self.run_results)} "
            f"success={self.success_rate:.0%} "
            f"decision={self.final_decision}>"
        )
