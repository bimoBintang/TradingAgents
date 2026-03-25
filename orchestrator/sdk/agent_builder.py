"""
AgentBuilder — Decorator-based SDK for building custom agents.

Provides a clean, intuitive API to define agents and tools without
needing to know the internals of the orchestration platform.

Usage:
    from orchestrator.sdk import agent, tool

    @tool(name="get_price", category="market")
    def get_price(ticker: str) -> float:
        return fetch_binance_price(ticker)

    @agent(role="Market Analyst", priority=10)
    async def market_analyst(state, bus, tools, **kwargs):
        price = tools.get_for_agent(["market"])["get_price"](ticker=state.ticker)
        state.set("analysis", "price", price, writer="market_analyst")
        return {"price": price, "signal": "BUY"}

    # These decorated functions can be passed directly to an Orchestrator:
    from orchestrator.orchestrator import Orchestrator
    from orchestrator.core import Topology

    orch = Orchestrator("BTCUSDT", topology=Topology.PIPELINE)
    orch.router.add_agent(**market_analyst.__agent_def__.to_router_kwargs())
    result = orch.run_sync()
"""

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentDefinition:
    """Metadata attached to a function decorated with @agent."""

    fn: Callable
    role: str
    agent_id: str
    depends_on: List[str]
    priority: int
    timeout: float
    description: str
    tags: List[str] = field(default_factory=list)

    def to_router_kwargs(self) -> dict:
        """Return kwargs suitable for TopologyRouter.add_agent()."""
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "handler": self.fn,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "timeout": self.timeout,
        }

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "timeout": self.timeout,
            "description": self.description,
            "tags": self.tags,
        }


@dataclass
class ToolDefinition:
    """Metadata attached to a function decorated with @tool."""

    fn: Callable
    name: str
    description: str
    category: str
    tags: List[str] = field(default_factory=list)
    requires_auth: bool = False

    def to_registry_kwargs(self) -> dict:
        """Return kwargs suitable for ToolRegistry.register()."""
        return {
            "name": self.name,
            "handler": self.fn,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "requires_auth": self.requires_auth,
        }


# ── Global registries (module-level) ─────────────────────────────────────────

_REGISTERED_AGENTS: Dict[str, AgentDefinition] = {}
_REGISTERED_TOOLS:  Dict[str, ToolDefinition]  = {}


def agent(
    role: str,
    agent_id: Optional[str] = None,
    depends_on: Optional[List[str]] = None,
    priority: int = 50,
    timeout: float = 120.0,
    description: str = "",
    tags: Optional[List[str]] = None,
):
    """
    Decorator that marks a function as an orchestration agent.

    The decorated function must have the signature:
        async def my_agent(state: StateManager, bus: AgentBus, tools: ToolRegistry, **kwargs) -> Any

    After decorating, the function gains an __agent_def__ attribute
    containing its AgentDefinition, and is registered globally.

    Example:
        @agent(role="Technical Analyst", priority=10)
        async def tech_analyst(state, bus, tools, **kwargs):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        _id = agent_id or fn.__name__
        doc = description or (fn.__doc__ or "").strip().split("\n")[0]

        defn = AgentDefinition(
            fn=fn,
            role=role,
            agent_id=_id,
            depends_on=depends_on or [],
            priority=priority,
            timeout=timeout,
            description=doc,
            tags=tags or [],
        )

        fn.__agent_def__ = defn
        _REGISTERED_AGENTS[_id] = defn
        logger.debug("[SDK] Registered agent '%s' (%s)", _id, role)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if asyncio.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            return fn(*args, **kwargs)

        wrapper.__agent_def__ = defn
        return wrapper

    return decorator


def tool(
    name: Optional[str] = None,
    description: str = "",
    category: str = "general",
    tags: Optional[List[str]] = None,
    requires_auth: bool = False,
):
    """
    Decorator that marks a function as an orchestration tool.

    Registered tools can be injected into any agent via ToolRegistry.

    Example:
        @tool(name="get_price", category="market")
        def get_price(ticker: str) -> float:
            return ...
    """
    def decorator(fn: Callable) -> Callable:
        _name = name or fn.__name__
        doc = description or (fn.__doc__ or "").strip().split("\n")[0]

        defn = ToolDefinition(
            fn=fn,
            name=_name,
            description=doc,
            category=category,
            tags=tags or [],
            requires_auth=requires_auth,
        )

        fn.__tool_def__ = defn
        _REGISTERED_TOOLS[_name] = defn
        logger.debug("[SDK] Registered tool '%s' (%s)", _name, category)
        return fn

    return decorator


# ── Registry Accessors ────────────────────────────────────────────────────────

def get_registered_agents() -> Dict[str, AgentDefinition]:
    """Return all globally registered agent definitions."""
    return dict(_REGISTERED_AGENTS)


def get_registered_tools() -> Dict[str, ToolDefinition]:
    """Return all globally registered tool definitions."""
    return dict(_REGISTERED_TOOLS)


def list_agents() -> List[dict]:
    """Return a formatted list of all registered agents."""
    return [defn.to_dict() for defn in _REGISTERED_AGENTS.values()]


def list_tools() -> List[dict]:
    """Return a formatted list of all registered tools."""
    return [
        {
            "name": defn.name,
            "category": defn.category,
            "description": defn.description,
            "tags": defn.tags,
        }
        for defn in _REGISTERED_TOOLS.values()
    ]


def build_orchestrator(
    ticker: str,
    topology: str = "pipeline",
    session_id: Optional[str] = None,
    agent_ids: Optional[List[str]] = None,
) -> Any:
    """
    Build an Orchestrator from all globally registered agents and tools.

    Args:
        ticker: The trading pair (e.g. "BTCUSDT")
        topology: "pipeline", "hierarchical", or "mesh"
        agent_ids: Optional filter — only include these agent IDs

    Returns:
        A configured Orchestrator instance ready to run.
    """
    from orchestrator.orchestrator import Orchestrator
    from orchestrator.core import Topology

    topo_map = {
        "pipeline": Topology.PIPELINE,
        "hierarchical": Topology.HIERARCHICAL,
        "mesh": Topology.MESH,
    }
    topo = topo_map.get(topology.lower(), Topology.PIPELINE)
    orch = Orchestrator(ticker=ticker, topology=topo, session_id=session_id)

    # Register tools
    for tool_defn in _REGISTERED_TOOLS.values():
        orch.tools.register(**tool_defn.to_registry_kwargs())

    # Register agents (optionally filtered)
    agents_to_add = (
        {aid: _REGISTERED_AGENTS[aid] for aid in agent_ids if aid in _REGISTERED_AGENTS}
        if agent_ids else _REGISTERED_AGENTS
    )
    for agent_defn in agents_to_add.values():
        orch.router.add_agent(**agent_defn.to_router_kwargs())
        orch.bus.register_agent(agent_defn.agent_id, agent_defn.role)

    logger.info(
        "[SDK] Built orchestrator: ticker=%s topology=%s agents=%d tools=%d",
        ticker, topology, len(agents_to_add), len(_REGISTERED_TOOLS),
    )
    return orch
