"""
TopologyRouter — Controls how agents are organized and sequenced.

Supports three core topologies:
  - PIPELINE   : Linear chain  A → B → C → D
  - HIERARCHICAL: Boss assigns tasks to workers, collects results
  - MESH       : All agents communicate freely, broadcast-style
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .agent_bus import AgentBus, Message
from .state_manager import StateManager

logger = logging.getLogger(__name__)


class Topology(str, Enum):
    PIPELINE = "pipeline"
    HIERARCHICAL = "hierarchical"
    MESH = "mesh"


@dataclass
class AgentNode:
    """Represents a registered agent in the topology graph."""

    agent_id: str
    role: str
    handler: Callable        # async fn(state, bus, **kwargs) -> Any
    depends_on: List[str] = field(default_factory=list)  # agent_ids that must run first
    priority: int = 50       # 0 (highest) to 100 (lowest)
    timeout: float = 120.0   # seconds before agent is considered timed out


@dataclass
class RunResult:
    """Result of running a single agent node."""

    agent_id: str
    role: str
    output: Any
    success: bool
    duration_seconds: float
    error: Optional[str] = None


class TopologyRouter:
    """
    Orchestrator that runs agents in a configured topology.

    Usage:
        router = TopologyRouter(topology=Topology.PIPELINE)
        router.add_agent("technical", "Technical Analyst", ta_handler)
        router.add_agent("quant", "Quant Analyst", quant_handler, depends_on=["technical"])

        results = await router.run(state, bus)
    """

    def __init__(
        self,
        topology: Topology = Topology.PIPELINE,
        max_concurrent: int = 5,
    ):
        self.topology = topology
        self.max_concurrent = max_concurrent
        self._agents: Dict[str, AgentNode] = {}

    # ── Agent Registration ────────────────────────────────────────────

    def add_agent(
        self,
        agent_id: str,
        role: str,
        handler: Callable,
        depends_on: Optional[List[str]] = None,
        priority: int = 50,
        timeout: float = 120.0,
    ) -> None:
        """Register an agent node in the topology."""
        self._agents[agent_id] = AgentNode(
            agent_id=agent_id,
            role=role,
            handler=handler,
            depends_on=depends_on or [],
            priority=priority,
            timeout=timeout,
        )
        logger.info(
            "[Router] Registered agent '%s' (%s) in %s topology",
            agent_id, role, self.topology.value,
        )

    def remove_agent(self, agent_id: str) -> None:
        """Remove an agent from the topology."""
        self._agents.pop(agent_id, None)

    # ── Execution ─────────────────────────────────────────────────────

    async def run(
        self,
        state: StateManager,
        bus: AgentBus,
        **kwargs,
    ) -> List[RunResult]:
        """Execute all agents according to the configured topology."""
        logger.info(
            "[Router] Starting %s topology for session '%s' (%d agents)",
            self.topology.value, state.session_id, len(self._agents),
        )

        if self.topology == Topology.PIPELINE:
            return await self._run_pipeline(state, bus, **kwargs)
        elif self.topology == Topology.HIERARCHICAL:
            return await self._run_hierarchical(state, bus, **kwargs)
        elif self.topology == Topology.MESH:
            return await self._run_mesh(state, bus, **kwargs)
        else:
            raise ValueError(f"Unknown topology: {self.topology}")

    # ── Pipeline Topology ─────────────────────────────────────────────

    async def _run_pipeline(
        self, state: StateManager, bus: AgentBus, **kwargs
    ) -> List[RunResult]:
        """Run agents sequentially in dependency-resolved order."""
        ordered = self._topological_sort()
        results = []
        for node in ordered:
            result = await self._invoke_agent(node, state, bus, **kwargs)
            results.append(result)
            if result.success:
                state.record_agent_output(node.agent_id, result.output)
                await bus.publish(Message(
                    topic=f"agent.output.{node.agent_id}",
                    sender=node.agent_id,
                    payload=result.output,
                    session_id=state.session_id,
                ))
            else:
                logger.warning("[Router] Pipeline agent '%s' failed: %s", node.agent_id, result.error)
        return results

    # ── Hierarchical Topology ─────────────────────────────────────────

    async def _run_hierarchical(
        self, state: StateManager, bus: AgentBus, **kwargs
    ) -> List[RunResult]:
        """
        Boss agents (depends_on=[]) run first, then workers run in
        parallel, then collectors run last.
        """
        ordered = self._topological_sort()
        results = []
        pending: List[AgentNode] = []

        for node in ordered:
            if not node.depends_on:
                # Boss — run immediately
                result = await self._invoke_agent(node, state, bus, **kwargs)
                results.append(result)
                if result.success:
                    state.record_agent_output(node.agent_id, result.output)
            else:
                pending.append(node)

        # Run workers concurrently
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_with_sem(node: AgentNode):
            async with semaphore:
                return await self._invoke_agent(node, state, bus, **kwargs)

        worker_results = await asyncio.gather(
            *[run_with_sem(n) for n in pending], return_exceptions=False
        )
        for node, result in zip(pending, worker_results):
            if result.success:
                state.record_agent_output(node.agent_id, result.output)
            results.append(result)

        return results

    # ── Mesh Topology ─────────────────────────────────────────────────

    async def _run_mesh(
        self, state: StateManager, bus: AgentBus, **kwargs
    ) -> List[RunResult]:
        """Run all agents concurrently — maximum parallelism."""
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def run_with_sem(node: AgentNode):
            async with semaphore:
                result = await self._invoke_agent(node, state, bus, **kwargs)
                if result.success:
                    state.record_agent_output(node.agent_id, result.output)
                    await bus.publish(Message(
                        topic=f"agent.output.{node.agent_id}",
                        sender=node.agent_id,
                        payload=result.output,
                        session_id=state.session_id,
                    ))
                return result

        return await asyncio.gather(*[run_with_sem(n) for n in self._agents.values()])

    # ── Agent Invocation ──────────────────────────────────────────────

    async def _invoke_agent(
        self, node: AgentNode, state: StateManager, bus: AgentBus, **kwargs
    ) -> RunResult:
        """Invoke a single agent handler with timeout protection."""
        import time
        start = time.monotonic()
        logger.info("[Router] Invoking agent '%s' (%s)", node.agent_id, node.role)

        try:
            coro = node.handler(state=state, bus=bus, **kwargs)
            if not asyncio.iscoroutine(coro):
                output = coro  # sync handler
            else:
                output = await asyncio.wait_for(coro, timeout=node.timeout)

            duration = time.monotonic() - start
            logger.info("[Router] Agent '%s' completed in %.2fs", node.agent_id, duration)
            return RunResult(
                agent_id=node.agent_id,
                role=node.role,
                output=output,
                success=True,
                duration_seconds=duration,
            )

        except asyncio.TimeoutError:
            duration = time.monotonic() - start
            error = f"Timed out after {node.timeout}s"
            logger.error("[Router] Agent '%s' timed out", node.agent_id)
            return RunResult(
                agent_id=node.agent_id, role=node.role,
                output=None, success=False,
                duration_seconds=duration, error=error,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            logger.error("[Router] Agent '%s' raised %s: %s", node.agent_id, type(exc).__name__, exc)
            return RunResult(
                agent_id=node.agent_id, role=node.role,
                output=None, success=False,
                duration_seconds=duration, error=str(exc),
            )

    # ── Dependency Resolution ─────────────────────────────────────────

    def _topological_sort(self) -> List[AgentNode]:
        """Return agents in dependency order (Kahn's algorithm)."""
        in_degree: Dict[str, int] = {aid: 0 for aid in self._agents}
        adjacency: Dict[str, List[str]] = {aid: [] for aid in self._agents}

        for aid, node in self._agents.items():
            for dep in node.depends_on:
                if dep in self._agents:
                    adjacency[dep].append(aid)
                    in_degree[aid] += 1

        queue = sorted(
            [aid for aid, deg in in_degree.items() if deg == 0],
            key=lambda aid: self._agents[aid].priority,
        )
        order: List[AgentNode] = []

        while queue:
            current = queue.pop(0)
            order.append(self._agents[current])
            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
                    queue.sort(key=lambda aid: self._agents[aid].priority)

        if len(order) != len(self._agents):
            raise RuntimeError("Circular dependency detected in agent topology!")

        return order

    # ── Inspection ────────────────────────────────────────────────────

    def get_execution_plan(self) -> List[Tuple[str, str, List[str]]]:
        """Return the planned execution order as (agent_id, role, depends_on) tuples."""
        return [
            (n.agent_id, n.role, n.depends_on) for n in self._topological_sort()
        ]

    def summary(self) -> dict:
        return {
            "topology": self.topology.value,
            "max_concurrent": self.max_concurrent,
            "agents": len(self._agents),
            "agent_ids": list(self._agents.keys()),
        }
