"""
ToolRegistry — Centralized catalog of callable tools for agents.

Agents do not call external APIs directly. Instead they request
a named tool from the registry. This gives the orchestrator
full visibility and control over every external action.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Registered tool entry in the catalog."""

    name: str
    description: str
    handler: Callable     # fn(**kwargs) -> Any
    category: str = "general"
    requires_auth: bool = False
    tags: List[str] = field(default_factory=list)

    def __call__(self, **kwargs) -> Any:
        return self.handler(**kwargs)


class ToolRegistry:
    """
    Central catalog of tools that agents can call.

    Usage:
        registry = ToolRegistry()

        # Register a tool
        @registry.tool(name="get_price", category="market")
        def get_price(ticker: str) -> float:
            return fetch_binance_price(ticker)

        # Inject into an agent context
        tools = registry.get_for_agent(["market", "news"])

        # Agent calls a tool
        price = tools["get_price"](ticker="BTCUSDT")
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._call_counts: Dict[str, int] = {}

    # ── Registration ──────────────────────────────────────────────────

    def register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        category: str = "general",
        requires_auth: bool = False,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Register a callable tool."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            handler=handler,
            category=category,
            requires_auth=requires_auth,
            tags=tags or [],
        )
        self._call_counts[name] = 0
        logger.debug("[ToolRegistry] Registered tool '%s' (%s)", name, category)

    def tool(
        self,
        name: Optional[str] = None,
        description: str = "",
        category: str = "general",
        requires_auth: bool = False,
        tags: Optional[List[str]] = None,
    ):
        """Decorator shorthand for registering a tool."""
        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            doc = description or (fn.__doc__ or "").strip().split("\n")[0]
            self.register(
                name=tool_name,
                handler=fn,
                description=doc,
                category=category,
                requires_auth=requires_auth,
                tags=tags,
            )
            return fn
        return decorator

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        self._tools.pop(name, None)
        self._call_counts.pop(name, None)

    # ── Retrieval ─────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Return a tool by name, or None if not found."""
        return self._tools.get(name)

    def get_for_agent(
        self, categories: Optional[List[str]] = None
    ) -> Dict[str, Callable]:
        """
        Return a dict of {tool_name: callable} for agent injection.

        If categories is provided, only tools matching those categories
        are included. Otherwise all tools are returned.
        """
        tools = {}
        for name, defn in self._tools.items():
            if categories is None or defn.category in categories:
                def make_tracked_call(tool_name: str, tool_defn: ToolDefinition):
                    def tracked(**kwargs):
                        self._call_counts[tool_name] += 1
                        logger.debug("[ToolRegistry] Tool '%s' called", tool_name)
                        return tool_defn.handler(**kwargs)
                    tracked.__name__ = tool_name
                    tracked.__doc__ = tool_defn.description
                    return tracked
                tools[name] = make_tracked_call(name, defn)
        return tools

    def list_tools(
        self, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return a list of tool info dicts."""
        result = []
        for name, defn in self._tools.items():
            if category and defn.category != category:
                continue
            result.append({
                "name": name,
                "description": defn.description,
                "category": defn.category,
                "tags": defn.tags,
                "requires_auth": defn.requires_auth,
                "call_count": self._call_counts.get(name, 0),
            })
        return sorted(result, key=lambda t: t["category"])

    # ── Stats ─────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, int]:
        """Return call counts for each tool."""
        return dict(self._call_counts)

    def most_used(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """Return the N most frequently called tools."""
        sorted_tools = sorted(
            self._call_counts.items(), key=lambda x: x[1], reverse=True
        )
        return [
            {"name": name, "calls": count}
            for name, count in sorted_tools[:top_n]
        ]

    def summary(self) -> dict:
        return {
            "total_tools": len(self._tools),
            "categories": list({d.category for d in self._tools.values()}),
            "total_calls": sum(self._call_counts.values()),
        }
