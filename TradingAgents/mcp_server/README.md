# TradingAgents MCP Server

Exposes TradingAgents as an [MCP](https://modelcontextprotocol.io) server —
market data, portfolio, analysis, and (guarded) trading tools, callable from
Claude Desktop, Claude Code, or any other MCP client.

This is a **thin layer**: every tool here imports and calls code that
already exists in `tradingagents/` and `api/` — nothing is reimplemented,
so this can never silently drift out of sync with the REST API or the
dashboard.

## Tools

| Tool | Reads/Writes | Notes |
|---|---|---|
| `get_stock_data`, `get_indicators`, `get_fundamentals`, `get_balance_sheet`, `get_cashflow`, `get_income_statement`, `get_news`, `get_global_news`, `get_insider_transactions` | Read-only | Market data — wraps `tradingagents/agents/utils/*.py`'s LangChain tools |
| `read_portfolio`, `list_recent_trades`, `list_pending_orders` | Read-only | |
| `run_analysis(ticker, trade_date?)` | Writes a `TaskResult` row | Runs the multi-agent pipeline, no trading |
| `propose_trade(ticker, trade_date?)` | Writes `TaskResult` + `PendingOrder` | Analysis-only in effect — see **Safety model** |
| `approve_pending_order(idempotency_key)` | ⚠️ Can place a real broker order | See **Safety model** |
| `reject_pending_order(idempotency_key)` | Writes `PendingOrder` status | |

## Safety model

`propose_trade()` forces `execution_engine.require_confirmation = True`
on its own graph instance before doing anything else — **no matter what
the dashboard's `execution.require_confirmation` setting is**. It only
ever queues an order into the same pending-order approval flow the
dashboard uses (`api/routers/pending.py`); it never submits one.

`approve_pending_order()` is the *only* tool that can cause a live order,
and it requires an explicit `idempotency_key` the caller must already
have (from `propose_trade`/`list_pending_orders`'s output) — an LLM
should only call it after a human has explicitly confirmed that specific
order, never speculatively.

This contract is enforced in code (`tools_trading.py`) and covered by
`tests/test_mcp_server.py::test_propose_trade_forces_require_confirmation_even_if_disabled` —
don't weaken either without a very deliberate reason.

## Identity — who is "me"?

The MCP server has no login session of its own, so "which account's
portfolio am I reading/trading on" is resolved differently per transport:

- **stdio** (default, local, single user): fixed once per process, from
  (in priority order) the dashboard's Settings > MCP Server field →
  `TRADINGAGENTS_MCP_USER_EMAIL` in `.env` → the first user in the DB
  (with a warning). See `context.py`.
- **streamable-http** (remote, opt-in): resolved **per request** from a
  verified Clerk bearer token — the same identity provider the
  dashboard uses. See `auth.py`.

## Running it

**stdio** — for Claude Desktop/Code on your own machine (see the
project root's `.mcp.json` for the registered config):

```bash
uv run python -m mcp_server.server
```

**streamable-http** — for remote/multi-user access, authenticated:

```bash
MCP_TRANSPORT=streamable-http uv run python -m mcp_server.server
# optional: MCP_HTTP_HOST, MCP_HTTP_PORT (default 127.0.0.1:8765),
# MCP_HTTP_PUBLIC_URL (public base URL if behind a proxy/tunnel),
# CLERK_ISSUER_URL (defaults to the CLERK_JWKS_URL host)
```

Unauthenticated or invalid-token requests get `401` — verified in
`tests/test_mcp_server.py`.

**MCP Inspector** (interactive manual testing):

```bash
uv run mcp dev mcp_server/server.py
```

## Tests

```bash
uv run pytest tests/test_mcp_server.py -v
```

Covers: tool registration/annotations, identity resolution priority
(both transports), the Clerk token verifier, and the `propose_trade`
safety contract above.

## See also: TradingAgents as an MCP *client*

This README covers TradingAgents acting as an MCP **server**. The
reverse direction — TradingAgents *consuming* an external MCP server as
a market-data vendor — lives in
`tradingagents/dataflows/mcp_client.py`, wired into the existing
vendor-routing system (`data_vendors`/`tool_vendors` in
`default_config.py`'s `mcp_client` section, disabled by default). See
that file's module docstring and `tests/test_mcp_client_vendor.py`.
