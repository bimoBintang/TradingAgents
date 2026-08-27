"""Tests for the mcp_client data vendor — Fase 6 (TradingAgents as an
MCP *client*, consuming an external MCP server as a data vendor).

Kept to fast, subprocess-free unit tests (config wiring, error
handling, fallback behavior) — a real end-to-end round trip (spawning
an actual MCP server subprocess and calling a tool through it) was
verified manually against mcp_server/server.py itself; see
tradingagents/dataflows/mcp_client.py's module docstring. That's
deliberately not part of the automated suite: it's slow and depends on
`uv` being on PATH, which would make CI flaky for marginal benefit
over these unit tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows.interface import VENDOR_LIST, VENDOR_METHODS
from tradingagents.dataflows.mcp_client import (
    MCPVendorError,
    MCPVendorNotConfigured,
    call_mcp_tool,
    get_stock_data,
)


# ── Wiring into interface.py ─────────────────────────────────────────

def test_mcp_is_a_registered_vendor():
    assert "mcp" in VENDOR_LIST


def test_mcp_has_an_implementation_for_every_tool():
    for method, vendors in VENDOR_METHODS.items():
        assert "mcp" in vendors, f"'{method}' has no mcp vendor implementation"


# ── Disabled-by-default behavior ────────────────────────────────────

def test_disabled_by_default_raises_not_configured():
    """DEFAULT_CONFIG ships with mcp_client.enabled=False — calling the
    vendor without opting in must fail clearly, not silently no-op or
    hang trying to connect somewhere unconfigured.

    Patches the config explicitly (rather than relying on whatever the
    global config singleton currently holds) so this doesn't depend on
    test execution order."""
    with patch("tradingagents.dataflows.mcp_client._mcp_config", return_value={"enabled": False}):
        with pytest.raises(MCPVendorNotConfigured):
            get_stock_data("AAPL", "2026-08-01", "2026-08-05")


def test_route_to_vendor_falls_back_past_unconfigured_mcp():
    """route_to_vendor()'s fallback chain must treat an unconfigured mcp
    vendor the same way it treats a rate-limited one: skip to the next
    vendor, not crash the whole call.

    Replaces get_stock_data's whole vendor dict for the duration of the
    test (rather than adding a mock alongside the real alpha_vantage/
    messari/coingecko implementations) so this doesn't depend on
    unrelated vendors' own credentials/network being available."""
    from tradingagents.dataflows.interface import route_to_vendor

    fake_vendors = {
        "mcp": get_stock_data,  # real, unconfigured -> MCPVendorNotConfigured
        "yfinance": MagicMock(return_value="fallback data"),
    }
    with patch("tradingagents.dataflows.interface.get_vendor", return_value="mcp"), \
         patch("tradingagents.dataflows.mcp_client._mcp_config", return_value={"enabled": False}), \
         patch.dict(VENDOR_METHODS, {"get_stock_data": fake_vendors}, clear=False):
        result = route_to_vendor("get_stock_data", "AAPL", "2026-08-01", "2026-08-05")

    assert result == "fallback data"


# ── Config-driven tool-name mapping ─────────────────────────────────

def test_call_mcp_tool_maps_our_name_to_external_name(monkeypatch):
    from tradingagents.dataflows import mcp_client

    monkeypatch.setattr(
        mcp_client,
        "_mcp_config",
        lambda: {"enabled": True, "tool_map": {"get_stock_data": "external_quote_tool"}},
    )

    captured = {}

    async def fake_call_tool_async(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return "ok"

    monkeypatch.setattr(mcp_client, "_call_tool_async", fake_call_tool_async)

    result = call_mcp_tool("get_stock_data", symbol="AAPL")

    assert result == "ok"
    assert captured["tool_name"] == "external_quote_tool"
    assert captured["arguments"] == {"symbol": "AAPL"}


def test_call_mcp_tool_wraps_unexpected_errors():
    """A connection failure or malformed response shouldn't leak a raw,
    vendor-agnostic-code-unfriendly exception type up through
    route_to_vendor() — it should be a recognizable MCPVendorError."""
    from tradingagents.dataflows import mcp_client

    with patch.object(mcp_client, "_mcp_config", return_value={"enabled": True, "tool_map": {}}), \
         patch.object(mcp_client, "_build_server_target", side_effect=RuntimeError("connection refused")):
        with pytest.raises(MCPVendorError):
            call_mcp_tool("get_stock_data", symbol="AAPL")


# ── _build_server_target ────────────────────────────────────────────

def test_build_server_target_stdio_requires_command():
    from tradingagents.dataflows.mcp_client import _build_server_target

    with pytest.raises(MCPVendorNotConfigured):
        _build_server_target({"transport": "stdio"})  # no "command"


def test_build_server_target_http_requires_url():
    from tradingagents.dataflows.mcp_client import _build_server_target

    with pytest.raises(MCPVendorNotConfigured):
        _build_server_target({"transport": "streamable-http"})  # no "url"


def test_build_server_target_stdio_builds_params():
    from mcp import StdioServerParameters
    from tradingagents.dataflows.mcp_client import _build_server_target

    target = _build_server_target({"transport": "stdio", "command": "uv", "args": ["run", "server.py"]})

    assert isinstance(target, StdioServerParameters)
    assert target.command == "uv"
    assert target.args == ["run", "server.py"]
