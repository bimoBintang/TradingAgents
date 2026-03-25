"""WebSocket endpoints for real-time dashboard updates.

Endpoints:
    ws /ws/portfolio    — streams portfolio state every 5 seconds
    ws /ws/analysis/{id} — streams task progress until completed/failed

Auth: JWT passed via ?token= query parameter.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError

from api.ws_manager import manager
from api.database import SessionLocal
from api.models import User, PortfolioState, Position, TaskResult

logger = logging.getLogger("api.ws")

router = APIRouter(tags=["WebSocket"])

PORTFOLIO_PUSH_INTERVAL = 5  # seconds


# ── Auth helper ───────────────────────────────────────────────────────

async def _authenticate_ws(token: str) -> int | None:
    """Validate JWT token and return user_id, or None if invalid."""
    if not token:
        return None
    try:
        from api.auth import get_clerk_jwks
        jwks = get_clerk_jwks()
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        rsa_key = {}
        for key in jwks.get("keys", []):
            if key["kid"] == kid:
                rsa_key = {
                    "kty": key["kty"], "kid": key["kid"],
                    "use": key["use"], "n": key["n"], "e": key["e"],
                }
                break

        if not rsa_key:
            return None

        payload = jwt.decode(token, rsa_key, algorithms=["RS256"], options={"verify_aud": False})
        clerk_id = payload.get("sub")
        if not clerk_id:
            return None

        # Look up user in DB
        with SessionLocal() as db:
            user = db.query(User).filter(User.clerk_id == clerk_id).first()
            return user.id if user else None

    except (JWTError, Exception) as e:
        logger.debug("WS auth failed: %s", e)
        return None


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

            payload = {
                "type": "portfolio_update",
                "data": {
                    "cash_balance": ps.cash_balance if ps else 0.0,
                    "total_equity": ps.total_equity if ps else 0.0,
                    "total_pnl": ps.total_pnl if ps else 0.0,
                    "daily_pnl": ps.daily_pnl if ps else None,
                    "win_rate": ps.win_rate if ps else 0.0,
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

            # Include results if completed
            if task_row.status == "completed" and task_row.result_json:
                try:
                    payload["result"] = json.loads(task_row.result_json)
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
