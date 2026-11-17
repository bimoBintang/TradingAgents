"""
TradingAgents MCP Server.

Ini adalah layer TIPIS di atas tool LangChain yang sudah ada di
`tradingagents/agents/utils/*.py`. Tidak ada logic bisnis baru di sini —
semua fungsi diimpor langsung dari kode yang sudah dipakai agent LangGraph,
supaya tidak ada duplikasi/drift antara REST API, WebSocket, dan MCP.

Cara pakai (uji lokal dengan MCP Inspector):
    cd C:\\TradingAgents\\TradingAgents
    uv run mcp dev mcp_server/server.py

Cara pakai (stdio — default, untuk didaftarkan di Claude Desktop/Code
lokal, selalu sebagai pemilik tunggal, lihat context.py):
    uv run python -m mcp_server.server

Cara pakai (streamable-http, TANPA autentikasi — jangan buka ke jaringan luar):
    MCP_TRANSPORT=streamable-http uv run python -m mcp_server.server
    # opsional: MCP_HTTP_HOST, MCP_HTTP_PORT (default 127.0.0.1:8765)
"""

from __future__ import annotations

import logging
import os

from langchain_core.tools import StructuredTool

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.agents.utils.technical_indicators_tools import get_indicators
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_global_news,
    get_insider_transactions,
)

from mcp_server.tools_portfolio import (
    read_portfolio,
    list_recent_trades,
    run_analysis,
)
from mcp_server.tools_trading import (
    list_pending_orders,
    propose_trade,
    approve_pending_order,
    reject_pending_order,
)
from mcp_server.tools_autopilot import (
    get_autopilot_status,
    start_autopilot,
    pause_autopilot,
    resume_autopilot,
    set_watchlist,
    list_ai_decisions,
)
from mcp_server.tools_chart import (
    get_chart_state,
    set_chart_view,
    annotate_chart_patterns,
    highlight_price_level,
    clear_ai_highlights,
)

logger = logging.getLogger("mcp_server")

# ── Transport ──────────────────────────────────────────────────────────
#
# stdio (default): no network exposure. streamable-http (opt-in) has NO
# authentication; keep it bound to localhost / a private network.
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_HTTP_HOST = os.getenv("MCP_HTTP_HOST", "127.0.0.1")
MCP_HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "8765"))

_server_kwargs: dict = {}
if MCP_TRANSPORT == "streamable-http":
    logger.warning(
        "MCP streamable-http has NO authentication; listening on %s:%s. "
        "Do not expose it to untrusted networks.", MCP_HTTP_HOST, MCP_HTTP_PORT,
    )

mcp = MCPServer(
    name="tradingagents",
    title="TradingAgents",
    description=(
        "Tools from the TradingAgents multi-agent trading framework: "
        "read-only market data (OHLCV prices, technical indicators, "
        "fundamentals, news), portfolio/trade history, and the "
        "multi-agent analysis pipeline. Always acts as the single owner "
        "(see mcp_server/context.py)."
    ),
    version="0.5.0",
    **_server_kwargs,
)

# Tool LangChain (`@tool`-decorated) yang mau diekspos sebagai MCP tool.
# Tambahkan ke daftar ini kalau mau expose tool baru — jangan tulis ulang
# logic-nya di file ini.
_LANGCHAIN_TOOLS: list[StructuredTool] = [
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_global_news,
    get_insider_transactions,
]


def _register_langchain_tools() -> None:
    """Daftarkan setiap LangChain StructuredTool sebagai MCP tool.

    Kita pakai `tool.func` (fungsi Python asli di balik decorator @tool)
    supaya MCPServer bisa introspeksi signature aslinya sendiri (untuk
    generate JSON schema args), alih-alih memanggil lewat LangChain's
    `.invoke()` yang mengharapkan dict input.
    """
    for t in _LANGCHAIN_TOOLS:
        mcp.add_tool(t.func, name=t.name, description=t.description)
        logger.info("Registered MCP tool: %s", t.name)


_register_langchain_tools()

# Plain Python functions (not LangChain @tool) — Fase 2 (portfolio,
# trade history, analysis) and Fase 3 (trading, with approval
# guardrails — see mcp_server/tools_trading.py's module docstring).
# Registered directly since they were written for MCP, not for a
# LangGraph agent's tool-calling.
#
# `annotations` hints are advisory (MCP clients may surface them to
# the user, e.g. "this tool can take real-world action" warnings) —
# they are NOT the safety mechanism itself. The actual guardrail is
# in tools_trading.py: propose_trade() forces require_confirmation
# and only ever queues an order; approve_pending_order() is the sole
# path that can submit one, gated on an explicit idempotency_key.
# Genuinely read-only: no DB writes, no side effects.
_READ_ONLY_TOOLS = [read_portfolio, list_recent_trades, list_pending_orders, get_chart_state,
                    get_autopilot_status, list_ai_decisions]
# Writes an analysis/task record (and, for propose_trade, a queued
# PendingOrder) but never a broker order — not read-only, but not
# destructive either since nothing irreversible happens to the account.
# Fase 7's chart tools land here too: they change what's *displayed* on
# the user's own dashboard (never portfolio/order state), which is a
# real side effect but not one that can lose money or data — see
# tools_chart.py's module docstring for the scope boundary.
_NON_DESTRUCTIVE_WRITE_TOOLS = [
    run_analysis, propose_trade,
    pause_autopilot, resume_autopilot, set_watchlist,
    set_chart_view, annotate_chart_patterns, highlight_price_level, clear_ai_highlights,
]
# Can cause a real broker order (or reverse a proposal) — see the
# safety contract in tools_trading.py's module docstring.
_GUARDED_WRITE_TOOLS = [
    (approve_pending_order, ToolAnnotations(destructive_hint=True, idempotent_hint=True, open_world_hint=True)),
    (start_autopilot, ToolAnnotations(destructive_hint=True, idempotent_hint=False, open_world_hint=True)),
    (reject_pending_order, ToolAnnotations(destructive_hint=False, idempotent_hint=True, open_world_hint=False)),
]

for _fn in _READ_ONLY_TOOLS:
    mcp.add_tool(_fn, annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
    logger.info("Registered MCP tool: %s", _fn.__name__)

for _fn in _NON_DESTRUCTIVE_WRITE_TOOLS:
    mcp.add_tool(_fn, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
    logger.info("Registered MCP tool: %s", _fn.__name__)

for _fn, _annotations in _GUARDED_WRITE_TOOLS:
    mcp.add_tool(_fn, annotations=_annotations)
    logger.info("Registered MCP tool: %s", _fn.__name__)


def main() -> None:
    """Entry point for `tradingagents-mcp` (see pyproject.toml [project.scripts])."""
    if MCP_TRANSPORT == "streamable-http":
        mcp.run(transport="streamable-http", host=MCP_HTTP_HOST, port=MCP_HTTP_PORT)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
