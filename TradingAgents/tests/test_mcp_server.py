"""Tests for the MCP server (mcp_server/) — Fase 5.

Focused on the parts most likely to silently break and matter most:
tool registration/annotations, owner resolution, and the propose_trade() safety contract (see
mcp_server/tools_trading.py's module docstring) — it must ALWAYS
force require_confirmation=True on its graph's execution engine
before doing anything else, regardless of the dashboard's own
execution settings.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from api.models import User


# ── Tool registration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_tools_registered_with_expected_names():
    from mcp_server.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    expected = {
        # Fase 1 — market data
        "get_stock_data", "get_indicators", "get_fundamentals",
        "get_balance_sheet", "get_cashflow", "get_income_statement",
        "get_news", "get_global_news", "get_insider_transactions",
        # Fase 2 — portfolio & analysis
        "read_portfolio", "list_recent_trades", "run_analysis",
        # Fase 3 — trading
        "list_pending_orders", "propose_trade",
        "approve_pending_order", "reject_pending_order",
        # Fase 7 — chart control
        "get_chart_state", "set_chart_view", "annotate_chart_patterns",
        "highlight_price_level", "clear_ai_highlights",
        # Autopilot control + decisions
        "get_autopilot_status", "start_autopilot", "pause_autopilot", "resume_autopilot",
        "set_watchlist", "list_ai_decisions",
    }
    assert names == expected


@pytest.mark.asyncio
async def test_read_only_tools_are_annotated_read_only():
    from mcp_server.server import mcp

    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("read_portfolio", "list_recent_trades", "list_pending_orders", "get_chart_state",
                 "get_autopilot_status", "list_ai_decisions"):
        assert tools[name].annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_approve_pending_order_is_annotated_destructive():
    """The one tool that can place a real broker order must be flagged
    as such — this is an advisory hint for MCP clients, not the actual
    safety mechanism (that's the forced require_confirmation below),
    but a regression here would be a UX/trust footgun worth catching."""
    from mcp_server.server import mcp

    tools = {t.name: t for t in await mcp.list_tools()}
    ann = tools["approve_pending_order"].annotations
    assert ann.destructive_hint is True
    assert ann.read_only_hint is not True


def _make_user(email="someone@example.com", id=1):
    u = MagicMock(spec=User)
    u.id = id
    u.email = email
    return u


# ── Identity: always the single owner ──────────────────────────────

def test_resolve_mcp_user_is_the_owner():
    from mcp_server.context import resolve_mcp_user

    owner = MagicMock(spec=User)
    with patch("api.auth.get_or_create_owner", return_value=owner) as m:
        db = MagicMock()
        assert resolve_mcp_user(db) is owner
        m.assert_called_once_with(db)


# ── propose_trade() safety contract (Fase 3) ────────────────────────

def test_propose_trade_forces_confirmation_on_the_graph_that_runs():
    """Core safety guarantee: propose_trade must pass force_confirmation=True to the analysis task,
    which sets it on the graph that actually runs (not on an unrelated singleton)."""
    from mcp_server.tools_trading import propose_trade

    with patch("mcp_server.tools_trading.db_session") as mock_db_session, \
         patch("mcp_server.tools_trading.resolve_mcp_user", return_value=_make_user()), \
         patch("api.tasks.run_analysis_thread") as run_thread:
        mock_db = MagicMock()
        mock_db_session.return_value.__enter__.return_value = mock_db
        mock_db.refresh.side_effect = lambda row: None
        with patch("mcp_server.tools_trading._ANALYSIS_TIMEOUT_SECONDS", 0), \
             patch("mcp_server.tools_trading.time.sleep"):
            propose_trade("AAPL")

    assert run_thread.call_args.kwargs.get("force_confirmation") is True


def test_approve_and_reject_use_the_shared_service():
    from mcp_server import tools_trading as T
    from api.schemas import ApproveRejectResponse

    ok = ApproveRejectResponse(success=True, idempotency_key="k", status="APPROVED", message="done", order_id="o1")
    with patch("mcp_server.tools_trading.db_session"), \
         patch("mcp_server.tools_trading.resolve_mcp_user", return_value=_make_user()), \
         patch("api.services.pending_orders.approve", return_value=ok) as ap, \
         patch("api.services.pending_orders.reject", return_value=ok) as rj:
        assert "approved" in T.approve_pending_order("k")
        T.reject_pending_order("k")
    assert ap.call_count == 1 and rj.call_count == 1


def test_start_autopilot_refuses_without_any_goal():
    from mcp_server.tools_autopilot import start_autopilot
    assert start_autopilot().startswith("Refused")
