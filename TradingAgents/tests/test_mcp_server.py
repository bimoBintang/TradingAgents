"""Tests for the MCP server (mcp_server/) — Fase 5.

Focused on the parts most likely to silently break and matter most:
tool registration/annotations, the per-mode identity resolution
(config file > env var > first-user, stdio; per-request Clerk token,
HTTP), and the propose_trade() safety contract (see
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
    }
    assert names == expected


@pytest.mark.asyncio
async def test_read_only_tools_are_annotated_read_only():
    from mcp_server.server import mcp

    tools = {t.name: t for t in await mcp.list_tools()}
    for name in ("read_portfolio", "list_recent_trades", "list_pending_orders", "get_chart_state"):
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


# ── Identity resolution (stdio mode) ────────────────────────────────

@pytest.fixture
def mock_config_path(tmp_path):
    with patch("mcp_server.context.CONFIG_PATH", tmp_path / "agent_config.json") as p:
        yield p


@pytest.fixture
def no_authenticated_principal():
    """Simulate stdio mode: no bearer token in play."""
    with patch("mcp_server.context._authenticated_clerk_id", return_value=None):
        yield


def _make_user(email="someone@example.com", id=1):
    u = MagicMock(spec=User)
    u.id = id
    u.email = email
    return u


def test_resolve_mcp_user_prefers_config_file_over_env(mock_config_path, no_authenticated_principal, monkeypatch):
    from mcp_server.context import resolve_mcp_user

    mock_config_path.write_text(json.dumps({"mcp": {"user_email": "from-config@example.com"}}))
    monkeypatch.setenv("TRADINGAGENTS_MCP_USER_EMAIL", "from-env@example.com")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = _make_user("from-config@example.com")

    user = resolve_mcp_user(db)

    assert user.email == "from-config@example.com"


def test_resolve_mcp_user_falls_back_to_env_when_config_unset(mock_config_path, no_authenticated_principal, monkeypatch):
    from mcp_server.context import resolve_mcp_user

    # No config file written at all.
    monkeypatch.setenv("TRADINGAGENTS_MCP_USER_EMAIL", "from-env@example.com")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = _make_user("from-env@example.com")

    user = resolve_mcp_user(db)
    assert user.email == "from-env@example.com"


def test_resolve_mcp_user_falls_back_to_first_user(mock_config_path, no_authenticated_principal, monkeypatch, caplog):
    from mcp_server.context import resolve_mcp_user

    monkeypatch.delenv("TRADINGAGENTS_MCP_USER_EMAIL", raising=False)

    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = _make_user("first@example.com")

    user = resolve_mcp_user(db)
    assert user.email == "first@example.com"
    assert "defaulting to first user" in caplog.text


def test_resolve_mcp_user_raises_when_nothing_configured_and_no_users(mock_config_path, no_authenticated_principal, monkeypatch):
    from mcp_server.context import McpUserNotConfigured, resolve_mcp_user

    monkeypatch.delenv("TRADINGAGENTS_MCP_USER_EMAIL", raising=False)

    db = MagicMock()
    db.query.return_value.order_by.return_value.first.return_value = None

    with pytest.raises(McpUserNotConfigured):
        resolve_mcp_user(db)


# ── Identity resolution (streamable-http mode) ──────────────────────

def test_resolve_mcp_user_prefers_authenticated_principal_over_config(mock_config_path, monkeypatch):
    """A real authenticated caller (HTTP + Clerk token) must always win
    over the stdio config fallback — it's more correct, never a guess."""
    from mcp_server.context import resolve_mcp_user

    mock_config_path.write_text(json.dumps({"mcp": {"user_email": "configured@example.com"}}))

    with patch("mcp_server.context._authenticated_clerk_id", return_value="clerk_abc123"):
        with patch("api.auth.get_or_create_user_by_clerk_id") as mock_upsert:
            mock_upsert.return_value = _make_user("caller@example.com")
            db = MagicMock()

            user = resolve_mcp_user(db)

            mock_upsert.assert_called_once_with(db, "clerk_abc123")
            assert user.email == "caller@example.com"


# ── Clerk token verifier (Fase 4) ───────────────────────────────────

@pytest.mark.asyncio
async def test_clerk_token_verifier_rejects_invalid_token():
    from mcp_server.auth import ClerkTokenVerifier
    from api.auth import ClerkTokenInvalid

    with patch("mcp_server.auth.verify_clerk_jwt", side_effect=ClerkTokenInvalid("bad sig")):
        result = await ClerkTokenVerifier().verify_token("garbage")
    assert result is None


@pytest.mark.asyncio
async def test_clerk_token_verifier_accepts_valid_token():
    from mcp_server.auth import ClerkTokenVerifier

    with patch("mcp_server.auth.verify_clerk_jwt", return_value="clerk_xyz"):
        result = await ClerkTokenVerifier().verify_token("a.valid.jwt")

    assert result is not None
    assert result.subject == "clerk_xyz"


# ── propose_trade() safety contract (Fase 3) ────────────────────────

def test_propose_trade_forces_require_confirmation_even_if_disabled():
    """This is the core safety guarantee: no matter what the dashboard's
    execution.require_confirmation is set to, propose_trade() must flip
    this MCP server's own graph instance to True before doing anything
    else — see tools_trading.py's module docstring."""
    from mcp_server.tools_trading import propose_trade

    fake_engine = MagicMock()
    fake_engine.require_confirmation = False  # dashboard has auto-trading enabled
    fake_graph = MagicMock()
    fake_graph.execution_engine = fake_engine

    with patch("mcp_server.tools_trading._get_graph", return_value=fake_graph), \
         patch("mcp_server.tools_trading.db_session") as mock_db_session, \
         patch("mcp_server.tools_trading.resolve_mcp_user", return_value=_make_user()), \
         patch("api.tasks.run_analysis_thread"):

        mock_db = MagicMock()
        mock_db_session.return_value.__enter__.return_value = mock_db
        # Make the task look like it never completes, so we return early
        # via the timeout path without needing to simulate a full run.
        task_row = MagicMock()
        task_row.status = "running"
        mock_db.refresh.side_effect = lambda row: None

        with patch("mcp_server.tools_trading._ANALYSIS_TIMEOUT_SECONDS", 0), \
             patch("mcp_server.tools_trading.time.sleep"):
            propose_trade("AAPL")

    # The safety-critical assertion — independent of whatever the rest
    # of the (heavily mocked) pipeline returned.
    assert fake_engine.require_confirmation is True
