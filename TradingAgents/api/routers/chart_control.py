"""Chart control REST endpoints — thin wrappers over api/chart_control.py.

Exercised mainly by MCP tools (mcp_server/tools_chart.py), which import
the service functions directly rather than calling these routes over
HTTP (same pattern as portfolio/analysis/trading MCP tools). These
routes exist for parity, manual curl testing, and so a future frontend
feature ("ask AI to mark this level") has somewhere to call too.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api import chart_control as service
from api.auth import get_current_user
from api.models import User

router = APIRouter(prefix="/api/chart-control", tags=["Chart Control"])


class SetViewRequest(BaseModel):
    ticker: str
    timeframe: Optional[str] = None
    indicator: Optional[str] = None


class HighlightRequest(BaseModel):
    ticker: str
    price: float
    label: str
    color: Optional[str] = None


@router.get("/state")
async def get_state(user: User = Depends(get_current_user)):
    """Last-known ticker/timeframe/indicator the user's dashboard reported."""
    return {"state": service.get_chart_state(user.id)}


@router.post("/set-view")
async def set_view(body: SetViewRequest, user: User = Depends(get_current_user)):
    return await service.set_chart_view(user.id, body.ticker, body.timeframe, body.indicator)


@router.post("/annotate-patterns")
async def annotate_patterns(ticker: str, timeframe: str = "1d", user: User = Depends(get_current_user)):
    return await service.annotate_chart_patterns(user.id, ticker, timeframe)


@router.post("/highlight-price-level")
async def highlight_price_level(body: HighlightRequest, user: User = Depends(get_current_user)):
    return await service.highlight_price_level(
        user.id, body.ticker, body.price, body.label, body.color or "#f59e0b",
    )


@router.post("/clear-ai-highlights")
async def clear_ai_highlights(ticker: str, user: User = Depends(get_current_user)):
    return await service.clear_ai_highlights(user.id, ticker)
