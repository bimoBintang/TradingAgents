"""Portfolio endpoints — state, positions, exit triggers.

Multi-tenant: all endpoints require authentication and return
data scoped to the authenticated user's portfolio.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Dict, Any

from api.schemas import PortfolioResponse, PositionResponse, ExitTriggerResponse
from api.dependencies import get_graph
from api.auth import get_current_user
from api.models import User
from api.user_context import get_user_portfolio
from api.services.pnl import compute_daily_pnl

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Full portfolio state for the authenticated user."""
    ps = ctx["portfolio"]
    positions = [
        PositionResponse(
            ticker=p.ticker,
            side=p.side,
            quantity=p.quantity,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl or 0.0,
        )
        for p in ctx["positions"]
    ]
    return PortfolioResponse(
        cash_balance=ps.cash_balance,
        total_equity=ps.total_equity,
        total_pnl=ps.total_pnl,
        # Computed fresh from real trade timestamps, not ps.daily_pnl —
        # see api/services/pnl.py for why that stored value drifts into
        # "since last restart" rather than "today".
        daily_pnl=compute_daily_pnl(ctx["db"], ps.id, ctx["positions"]),
        win_rate=ps.win_rate,
        max_drawdown_pct=ps.max_drawdown_pct,
        total_trades=ps.total_trades,
        open_positions=positions,
    )


@router.get("/positions", response_model=List[PositionResponse])
async def get_positions(
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Open positions for the authenticated user."""
    return [
        PositionResponse(
            ticker=p.ticker,
            side=p.side,
            quantity=p.quantity,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl or 0.0,
        )
        for p in ctx["positions"]
    ]


@router.get("/exits", response_model=List[ExitTriggerResponse])
async def check_exits(
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
):
    """Check for position exit triggers (stop-loss, trailing, etc.)."""
    exits = graph.check_position_exits()
    return [
        ExitTriggerResponse(
            ticker=e.get("ticker", ""),
            trigger=e.get("trigger", ""),
            details=e.get("details"),
        )
        for e in (exits or [])
    ]
