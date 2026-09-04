"""
TradingView API Router for FastAPI backend.

Provides endpoints for:
1. GET  /api/tradingview/analysis: Combined quantitative TA & ChartVisionAgent report.
2. POST /api/tradingview/pinescript: Protected endpoint for Pine Script syntax validation & injection.
3. GET  /api/tradingview/mcp-status: CDP localhost (127.0.0.1:9222) connection health & fallback mode status.
"""

import sys
import os
import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

# Ensure sys.path includes orchestrator and project root
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from api.auth import get_current_user
from api.models import User
from api.database import get_db

from orchestrator.mcp.tradingview_mcp_client import TradingViewMCPClient
from orchestrator.tools import get_tradingview_analysis, tv_write_pinescript
from orchestrator.sdk import create_trading_orchestrator, chart_vision_agent_handler

logger = logging.getLogger("api.tradingview")

router = APIRouter(prefix="/api/tradingview", tags=["TradingView"])

_MCP_CLIENT = TradingViewMCPClient()


# ── Request / Response Schemas ──────────────────────────────────────────────

class PineScriptRequest(BaseModel):
    code: str = Field(..., description="Pine Script source code (v4/v5)")
    script_name: str = Field("CMAOP_Strategy", description="Name of the strategy/indicator")


class PineScriptResponse(BaseModel):
    status: str
    script_name: str
    compiled: bool
    message: str
    syntax_valid: bool = True


# ── Pine Script Syntax Validator ─────────────────────────────────────────────

def validate_pinescript_syntax(code: str) -> None:
    """
    Validate basic Pine Script syntax before attempting CDP injection.
    Raises HTTPException 400 if syntax is invalid.
    """
    if not code or not isinstance(code, str) or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script code cannot be empty."
        )

    code_clean = code.strip()

    # Check for basic declaration keyword
    has_definition = any(kw in code_clean for kw in ["indicator(", "strategy(", "library("])
    if not has_definition:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Pine Script structure: Code must contain an 'indicator()', 'strategy()', or 'library()' definition header."
        )

    # Check balanced parentheses & brackets & braces
    if code_clean.count("(") != code_clean.count(")"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script syntax error: Unbalanced parentheses '()' detected."
        )

    if code_clean.count("[") != code_clean.count("]"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script syntax error: Unbalanced brackets '[]' detected."
        )

    if code_clean.count("{") != code_clean.count("}"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script syntax error: Unbalanced curly braces '{}' detected."
        )

    # Check for unclosed quotes
    double_quotes = code_clean.replace('\\"', '').count('"')
    if double_quotes % 2 != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script syntax error: Unclosed double quotes '\"' detected."
        )

    single_quotes = code_clean.replace("\\'", '').count("'")
    if single_quotes % 2 != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pine Script syntax error: Unclosed single quotes \"'\" detected."
        )


# ── API Endpoints ────────────────────────────────────────────────────────────

@router.get("/mcp-status")
async def get_mcp_status():
    """
    Check TradingView Desktop CDP connection status (strictly 127.0.0.1:9222).
    """
    is_healthy = await _MCP_CLIENT.check_health_async()
    return {
        "cdp_host": "127.0.0.1",
        "cdp_port": 9222,
        "is_connected": is_healthy,
        "mode": "LIVE_CDP_DESKTOP" if is_healthy else "FALLBACK_QUANTITATIVE_TA",
        "fallback_active": not is_healthy,
        "message": "Live CDP connected to TradingView Desktop." if is_healthy else "CDP unreachable on 127.0.0.1:9222. Fallback mode active.",
    }


@router.get("/analysis")
async def get_tradingview_analysis_data(
    ticker: str = "BTCUSDT",
    timeframe: str = "1h",
    exchange: str = "BINANCE",
    screener: str = "crypto",
):
    """
    Fetch combined TradingView quantitative indicators + ChartVisionAgent report.
    Uses 60s TTL caching layer to protect against rate-limits.
    """
    ticker_clean = ticker.strip().upper()

    try:
        # 1. Quantitative TA (Cached 60s)
        ta_data = get_tradingview_analysis(
            ticker=ticker_clean,
            exchange=exchange,
            screener=screener,
            interval=timeframe,
        )

        # 2. Run ChartVisionAgent
        orch = create_trading_orchestrator(ticker=ticker_clean, topology="pipeline")
        vision_report = await chart_vision_agent_handler(orch.state, orch.bus, orch.tools, timeframe=timeframe)

        return {
            "status": "success",
            "ticker": ticker_clean,
            "timeframe": timeframe,
            "quantitative_ta": ta_data,
            "chart_vision_report": vision_report,
        }
    except Exception as exc:
        logger.error("[API TradingView] Error fetching analysis for %s: %s", ticker_clean, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate TradingView analysis: {exc}"
        )


@router.post("/pinescript", response_model=PineScriptResponse)
async def inject_pinescript(
    body: PineScriptRequest,
    user: User = Depends(get_current_user),
):
    """
    Inject and verify Pine Script strategy in TradingView Desktop Pine Editor.
    Protected endpoint: Requires valid JWT authentication.
    """
    # 1. Syntax Validation (Dry-Run Check)
    validate_pinescript_syntax(body.code)

    try:
        # 2. Inject & Verify via CDP / Fallback Client
        res = tv_write_pinescript(code=body.code, script_name=body.script_name)
        # Defaults here are deliberately conservative (not "success"/True) —
        # tv_write_pinescript() always populates these itself, but a
        # response missing them shouldn't be read as an unearned success.
        return PineScriptResponse(
            status=res.get("status", "unknown"),
            script_name=body.script_name,
            compiled=res.get("compiled", False),
            syntax_valid=True,
            message=res.get("message", "No confirmation received from TradingView."),
        )
    except Exception as exc:
        logger.error("[API TradingView] Error injecting Pine Script by user %d: %s", user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to inject Pine Script: {exc}"
        )
