"""WebSocket endpoints for real-time dashboard updates.

Endpoints:
    ws /ws/portfolio      — streams portfolio state every 5 seconds
    ws /ws/ohlcv/{ticker} — streams live candles from the user's connected
                            exchange every few seconds (live ccxt only)
    ws /ws/analysis/{id}  — streams task progress until completed/failed
    ws /ws/chart-control  — bidirectional: dashboard reports chart state,
                            MCP-driven commands (api/chart_control.py) pushed in

Auth: JWT passed via ?token= query parameter.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.concurrency import run_in_threadpool

from api import chart_control
from api.auth import ClerkTokenInvalid, verify_clerk_jwt
from api.ws_manager import manager
from api.database import SessionLocal
from api.models import User, PortfolioState, Position, TaskResult
from api.services.pnl import compute_daily_pnl

logger = logging.getLogger("api.ws")

router = APIRouter(tags=["WebSocket"])

PORTFOLIO_PUSH_INTERVAL = 5  # seconds
OHLCV_PUSH_INTERVAL = 8      # seconds — real-time-feeling, gentle on exchange rate limits


# ── Auth helper ───────────────────────────────────────────────────────

async def _authenticate_ws(token: str) -> int | None:
    """Validate JWT token and return user_id, or None if invalid.

    Reuses api/auth.py's verify_clerk_jwt — this used to carry its own
    copy of the JWKS-lookup/decode logic (a second one, alongside
    api/auth.py's and, before Fase 4, a would-be third in
    mcp_server/auth.py) which had already drifted slightly (no `kty`
    fallback handling differences aside). One implementation now.
    """
    if not token:
        return None
    try:
        clerk_id = verify_clerk_jwt(token)
    except ClerkTokenInvalid as e:
        logger.debug("WS auth failed: %s", e)
        return None

    with SessionLocal() as db:
        user = db.query(User).filter(User.clerk_id == clerk_id).first()
        return user.id if user else None


# ── Portfolio Feed ────────────────────────────────────────────────────

@router.websocket("/ws/portfolio")
async def ws_portfolio(websocket: WebSocket, token: str = Query("")):
    """Stream portfolio state to the authenticated user every 5 seconds."""
    user_id = await _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Read portfolio from DB
            with SessionLocal() as db:
                ps = db.query(PortfolioState).filter(PortfolioState.user_id == user_id).first()
                positions = []
                pos_rows = []
                if ps:
                    pos_rows = db.query(Position).filter(Position.portfolio_id == ps.id).all()
                    positions = [
                        {
                            "ticker": p.ticker,
                            "side": p.side,
                            "quantity": p.quantity,
                            "entry_price": p.entry_price,
                            "current_price": p.current_price,
                            "unrealized_pnl": p.unrealized_pnl or 0.0,
                        }
                        for p in pos_rows
                    ]
                # Computed fresh each tick from real trade timestamps —
                # see api/services/pnl.py for why ps.daily_pnl itself
                # isn't used (it drifts into "since last restart").
                daily_pnl = compute_daily_pnl(db, ps.id, pos_rows) if ps else None

            payload = {
                "type": "portfolio_update",
                "data": {
                    "cash_balance": ps.cash_balance if ps else 0.0,
                    "total_equity": ps.total_equity if ps else 0.0,
                    "total_pnl": ps.total_pnl if ps else 0.0,
                    "daily_pnl": daily_pnl,
                    "win_rate": ps.win_rate if ps else 0.0,
                    "max_drawdown_pct": ps.max_drawdown_pct if ps else 0.0,
                    "total_trades": ps.total_trades if ps else 0,
                    "positions": positions,
                },
            }

            await manager.send_json(user_id, payload)
            await asyncio.sleep(PORTFOLIO_PUSH_INTERVAL)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WS portfolio error (user=%d): %s", user_id, e)
    finally:
        await manager.disconnect(websocket, user_id)


# ── Live OHLCV Feed ───────────────────────────────────────────────────
#
# Only active when the user has a live ccxt broker with a real exchange
# selected — closes immediately otherwise so ChartPanel.tsx falls back to
# its existing yfinance-backed REST polling (useOHLCV) unchanged. This is
# additive: it never replaces that path, only supersedes it when it's the
# more accurate source (the exchange the bot actually trades on).

@router.websocket("/ws/ohlcv/{ticker}")
async def ws_ohlcv(websocket: WebSocket, ticker: str, timeframe: str = Query("1h"), token: str = Query("")):
    """Stream live candles for `ticker` from the user's connected exchange."""
    user_id = await _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    from api.user_context import get_user_config
    with SessionLocal() as db:
        exec_cfg = get_user_config(db, user_id).get("execution", {})

    exchange_id = exec_cfg.get("exchange") if exec_cfg.get("broker") == "ccxt" else None
    if not exchange_id:
        # No live exchange configured — nothing for this feed to source
        # from. Close with a distinct code so the frontend can tell "not
        # applicable" apart from "server error" and stay silently on yfinance.
        await websocket.close(code=4004, reason="No live exchange configured")
        return

    quote = exec_cfg.get("quote_currency", "USDT")

    await manager.connect(websocket, user_id)
    last_candle_time = None
    try:
        while True:
            try:
                from tradingagents.dataflows.ccxt_ohlcv import fetch_ohlcv
                candles = await run_in_threadpool(fetch_ohlcv, exchange_id, ticker, timeframe, 200, quote)
                if candles and candles[-1]["time"] != last_candle_time:
                    last_candle_time = candles[-1]["time"]
                    await manager.send_json(user_id, {
                        "type": "ohlcv_update",
                        "ticker": ticker.upper(),
                        "exchange": exchange_id,
                        "timeframe": timeframe,
                        "candles": candles,
                    })
            except Exception as e:
                # A single failed fetch (rate limit, transient network
                # error, bad symbol) shouldn't kill the whole feed — log
                # and retry on the next tick. useOHLCV's yfinance data
                # keeps rendering underneath in the meantime.
                logger.warning("WS ohlcv fetch failed for %s@%s: %s", ticker, exchange_id, e)

            await asyncio.sleep(OHLCV_PUSH_INTERVAL)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WS ohlcv error (user=%d, ticker=%s): %s", user_id, ticker, e)
    finally:
        await manager.disconnect(websocket, user_id)


# ── Analysis Progress ────────────────────────────────────────────────

@router.websocket("/ws/analysis/{task_id}")
async def ws_analysis(websocket: WebSocket, task_id: str, token: str = Query("")):
    """Stream analysis task progress until completed or failed."""
    user_id = await _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            with SessionLocal() as db:
                task_row = (
                    db.query(TaskResult)
                    .filter(TaskResult.task_id == task_id, TaskResult.user_id == user_id)
                    .first()
                )

            if not task_row:
                await websocket.send_json({
                    "type": "analysis_status",
                    "task_id": task_id,
                    "status": "not_found",
                })
                break

            payload = {
                "type": "analysis_status",
                "task_id": task_id,
                "status": task_row.status,
                "ticker": task_row.ticker,
            }

            # Include results if completed — flat shape (decision/
            # order_result/reports at the top level), matching
            # AnalysisResultResponse from GET /api/analyze/{task_id}
            # exactly. This used to nest everything under payload["result"]
            # instead, while the frontend (AnalysisPage.tsx) reads
            # rawData?.decision directly — so whenever this WS was the
            # active source (its "LIVE" badge on), the results section
            # silently never rendered even though status correctly showed
            # "completed". decision also goes through the same
            # _parse_decision() normalization as the REST endpoint — see
            # its docstring in api/routers/analysis.py for why that matters.
            if task_row.status == "completed" and task_row.result_json:
                try:
                    from api.routers.analysis import _parse_decision
                    result = json.loads(task_row.result_json)
                    decision = _parse_decision(result.get("decision"))
                    payload["decision"] = decision.model_dump() if decision else None
                    payload["order_result"] = result.get("order_result")
                    payload["reports"] = result.get("reports")
                except json.JSONDecodeError:
                    pass
            elif task_row.status == "failed":
                payload["error"] = task_row.error

            await websocket.send_json(payload)

            # Stop polling if terminal state
            if task_row.status in ("completed", "failed"):
                break

            await asyncio.sleep(2)  # Poll every 2s

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WS analysis error (user=%d, task=%s): %s", user_id, task_id, e)
    finally:
        await manager.disconnect(websocket, user_id)


# ── Chart Control (Fase 7) ───────────────────────────────────────────
#
# Bidirectional, unlike the two feeds above:
#   dashboard → backend: {"type": "chart_state", "data": {ticker, timeframe, activeIndicator}}
#       Cached in api/chart_control.py so MCP's get_chart_state() tool
#       (and GET /api/chart-control/state) can read it back.
#   backend → dashboard: {"type": "chart_command", "action": ..., ...}
#       Pushed by api/chart_control.py (called from MCP tools or the
#       REST router) via the same ConnectionManager used above.

@router.websocket("/ws/chart-control")
async def ws_chart_control(websocket: WebSocket, token: str = Query("")):
    """Dashboard-side channel for MCP-driven chart control.

    Only reports/receives — this endpoint itself never touches the DB
    or a broker; it's ephemeral UI state, not domain data. See
    api/chart_control.py's module docstring for the full picture.
    """
    user_id = await _authenticate_ws(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "chart_state":
                chart_control.record_chart_state(user_id, msg.get("data") or {})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WS chart-control error (user=%d): %s", user_id, e)
    finally:
        await manager.disconnect(websocket, user_id)
