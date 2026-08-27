"""MCP-client data vendor — Fase 6 (TradingAgents as an MCP *client*).

Lets TradingAgents consume ANY external MCP server as a market-data
vendor, selectable exactly the same way as yfinance/alpha_vantage/
messari/coingecko — via `data_vendors`/`tool_vendors` in
agent_config.json, or as a fallback in interface.py's
`route_to_vendor()`. This is generic client-side infrastructure, not a
hardcoded integration with one specific external provider: point it at
whichever MCP data server you want via the `mcp_client` config section
(see default_config.py).

Config shape (default_config.py's "mcp_client"):
    {
        "enabled": False,
        "transport": "stdio",          # or "streamable-http"
        "command": None, "args": [],   # stdio: subprocess to launch
        "url": None, "headers": {},    # streamable-http: remote server
        "tool_map": {                  # our tool name -> theirs
            "get_stock_data": "get_stock_data",
            ...
        },
    }

Not wired into DEFAULT_CONFIG's data_vendors/tool_vendors by default
(enabled=False) — this is infrastructure to opt into per-tool via
config once you have a real external MCP data server to point it at,
not an always-on vendor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .config import get_config

logger = logging.getLogger(__name__)


class MCPVendorNotConfigured(RuntimeError):
    """The mcp_client vendor was selected but isn't enabled/configured.

    Caught in interface.py's route_to_vendor() fallback chain the same
    way rate-limit errors are — so an unconfigured MCP vendor just
    falls through to the next available vendor instead of hard-failing.
    """


class MCPVendorError(RuntimeError):
    """The external MCP server call itself failed (connection, tool error, etc.)."""


def _mcp_config() -> dict:
    return get_config().get("mcp_client", {})


def _build_server_target(cfg: dict):
    """Build the `server` argument mcp.client.Client expects."""
    from mcp import StdioServerParameters

    transport = cfg.get("transport", "stdio")
    if transport == "streamable-http":
        url = cfg.get("url")
        if not url:
            raise MCPVendorNotConfigured("mcp_client.url is required for transport='streamable-http'")
        return url
    if transport == "stdio":
        command = cfg.get("command")
        if not command:
            raise MCPVendorNotConfigured("mcp_client.command is required for transport='stdio'")
        return StdioServerParameters(command=command, args=cfg.get("args") or [], env=cfg.get("env"))
    raise MCPVendorNotConfigured(f"Unsupported mcp_client.transport: {transport!r}")


async def _call_tool_async(tool_name: str, arguments: dict[str, Any]) -> str:
    from mcp.client import Client

    cfg = _mcp_config()
    if not cfg.get("enabled"):
        raise MCPVendorNotConfigured(
            "mcp_client vendor selected but not enabled — set mcp_client.enabled=true "
            "and configure command/args (stdio) or url (streamable-http) in "
            "agent_config.json."
        )
    server = _build_server_target(cfg)

    async with Client(server) as client:
        result = await client.call_tool(tool_name, arguments)

    if result.is_error:
        raise MCPVendorError(f"MCP tool {tool_name!r} returned an error: {result.content!r}")

    texts = [getattr(block, "text", "") for block in result.content]
    return "\n".join(t for t in texts if t)


def call_mcp_tool(our_method: str, **arguments: Any) -> str:
    """Call the external MCP server's tool mapped to `our_method`, synchronously.

    Uses a fresh connection per call — simpler and safer than sharing
    one long-lived async client across the sync call sites in
    interface.py's VENDOR_METHODS, and these are request-shaped calls
    (not a hot loop), so the reconnect cost is a fine tradeoff.

    Args:
        our_method: One of TradingAgents' own tool names (get_stock_data,
            get_fundamentals, ...) — looked up in mcp_client.tool_map to
            find the external server's tool name (defaults to the same
            name if unmapped).
        **arguments: Forwarded as the MCP tool call's arguments dict.

    Raises:
        MCPVendorNotConfigured: vendor disabled or missing required config.
        MCPVendorError: the connection or tool call itself failed.
    """
    cfg = _mcp_config()
    tool_name = (cfg.get("tool_map") or {}).get(our_method, our_method)

    try:
        return asyncio.run(_call_tool_async(tool_name, arguments))
    except MCPVendorNotConfigured:
        raise
    except Exception as e:
        raise MCPVendorError(f"MCP call to '{tool_name}' failed: {e}") from e


# ── Per-method wrappers ──────────────────────────────────────────────
#
# Positional signatures deliberately match the other vendor
# implementations for the same method in interface.py's
# VENDOR_METHODS (e.g. y_finance.get_YFin_data_online), so
# route_to_vendor()'s fallback chain can call any vendor
# interchangeably.

def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    return call_mcp_tool("get_stock_data", symbol=symbol, start_date=start_date, end_date=end_date)


def get_indicators(symbol: str, indicator: str, curr_date: str, look_back_days: int) -> str:
    return call_mcp_tool(
        "get_indicators", symbol=symbol, indicator=indicator,
        curr_date=curr_date, look_back_days=look_back_days,
    )


def get_fundamentals(ticker: str, curr_date: Optional[str] = None) -> str:
    return call_mcp_tool("get_fundamentals", ticker=ticker, curr_date=curr_date)


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return call_mcp_tool("get_balance_sheet", ticker=ticker, freq=freq, curr_date=curr_date)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return call_mcp_tool("get_cashflow", ticker=ticker, freq=freq, curr_date=curr_date)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: Optional[str] = None) -> str:
    return call_mcp_tool("get_income_statement", ticker=ticker, freq=freq, curr_date=curr_date)


def get_insider_transactions(ticker: str) -> str:
    return call_mcp_tool("get_insider_transactions", ticker=ticker)


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    return call_mcp_tool("get_news", ticker=ticker, start_date=start_date, end_date=end_date)


def get_global_news(curr_date: str, look_back_days: int = 7, limit: int = 10) -> str:
    return call_mcp_tool("get_global_news", curr_date=curr_date, look_back_days=look_back_days, limit=limit)
