"""Journal endpoints — trades, performance, equity curve, rejections, CSV export.

Multi-tenant: all endpoints require authentication and return
data scoped to the authenticated user's trade history.
"""

import math
import csv
from io import StringIO
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from typing import List, Optional, Dict, Any

from api.schemas import (
    TradeResponse,
    PerformanceResponse,
    EquityPointResponse,
)
from api.dependencies import get_graph
from api.auth import get_current_user
from api.models import User
from api.user_context import get_user_portfolio

router = APIRouter(prefix="/api/journal", tags=["Journal"])


def _trades_from_ctx(ctx: Dict[str, Any], ticker=None, action=None) -> List[dict]:
    """Extract trade dicts from user context (DB-backed)."""
    trades = []
    for t in ctx["trades"]:
        trade_dict = {
            "ticker": t.ticker,
            "action": t.action,
            "filled_qty": t.filled_qty,
            "fill_price": t.fill_price,
            "realized_pnl": t.realized_pnl,
            "status": t.status,
            "fill_time": t.fill_time.isoformat() if t.fill_time else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        if ticker and trade_dict["ticker"] != ticker:
            continue
        if action and trade_dict["action"] != action:
            continue
        trades.append(trade_dict)
    return trades


@router.get("/trades", response_model=List[TradeResponse])
async def get_trades(
    ticker: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Query trades for the authenticated user with optional filters."""
    trades = _trades_from_ctx(ctx, ticker=ticker, action=action)

    if start_date:
        trades = [t for t in trades if (t.get("fill_time") or "") >= start_date]
    if end_date:
        trades = [t for t in trades if (t.get("fill_time") or "") <= end_date]

    return [TradeResponse(**t) for t in trades]


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Performance report for the authenticated user."""
    trades = _trades_from_ctx(ctx)

    if not trades:
        return PerformanceResponse()

    pnls = [t["realized_pnl"] for t in trades if t.get("realized_pnl") is not None]

    if not pnls:
        return PerformanceResponse()

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    total = len(pnls)

    win_rate = len(wins) / total if total else 0.0
    avg_pnl = sum(pnls) / total

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    sharpe = 0.0
    if len(pnls) > 1:
        mean_r = sum(pnls) / len(pnls)
        std_r = math.sqrt(sum((p - mean_r) ** 2 for p in pnls) / (len(pnls) - 1))
        sharpe = mean_r / std_r if std_r > 0 else 0.0

    ps = ctx["portfolio"]
    return PerformanceResponse(
        total_trades=total,
        win_rate=round(win_rate, 4),
        profit_factor=round(min(profit_factor, 999.0), 4),
        sharpe_ratio=round(sharpe, 4),
        max_drawdown=round(ps.max_drawdown_pct or 0.0, 4),
        avg_pnl=round(avg_pnl, 2),
        best_trade=round(max(pnls), 2),
        worst_trade=round(min(pnls), 2),
    )


@router.get("/equity-curve", response_model=List[EquityPointResponse])
async def get_equity_curve(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Equity curve for the authenticated user."""
    trades = _trades_from_ctx(ctx)
    if not trades:
        return []

    ps = ctx["portfolio"]
    initial_cash = ps.cash_balance + ps.total_pnl  # approximate initial
    equity = initial_cash

    sorted_trades = sorted(trades, key=lambda t: t.get("fill_time") or "")

    daily: dict = defaultdict(float)
    for t in sorted_trades:
        date = (t.get("fill_time") or "")[:10]
        if date:
            daily[date] += t.get("realized_pnl", 0) or 0

    curve = []
    for date in sorted(daily.keys()):
        if start_date and date < start_date:
            equity += daily[date]
            continue
        if end_date and date > end_date:
            break
        equity += daily[date]
        curve.append(EquityPointResponse(
            timestamp=f"{date}T00:00:00",
            total_equity=round(equity, 2),
            cash=round(ps.cash_balance, 2),
            drawdown_pct=round(ps.max_drawdown_pct or 0.0, 4),
        ))

    return curve


@router.get("/rejections")
async def get_rejections(
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
):
    """Rejection stats by code."""
    if not graph.journal:
        return {}
    try:
        return graph.journal.get_rejection_stats()
    except Exception:
        return {}


@router.get("/export")
async def export_csv(
    ctx: Dict[str, Any] = Depends(get_user_portfolio),
):
    """Download authenticated user's trades as CSV."""
    trades = _trades_from_ctx(ctx)

    if not trades:
        return StreamingResponse(
            iter(["no trades"]),
            media_type="text/plain",
            status_code=204,
        )

    buf = StringIO()
    fieldnames = list(trades[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(trades)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )

# ── Daily Notes ────────────────────────────────────────────────────────

from api.database import get_db
from sqlalchemy.orm import Session
from api.models import JournalNote
from api.schemas import JournalNoteCreate, JournalNoteResponse

@router.get("/notes", response_model=JournalNoteResponse)
async def get_note(
    date: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the journal note for a specific date (YYYY-MM-DD)."""
    note = db.query(JournalNote).filter(
        JournalNote.user_id == user.id,
        JournalNote.date == date
    ).first()
    
    if not note:
        # Return an empty note if none exists yet
        return JournalNoteResponse(
            id=0, date=date, content="", 
            created_at=datetime.utcnow(), 
            updated_at=datetime.utcnow()
        )
    return note


@router.get("/notes/history", response_model=List[JournalNoteResponse])
async def get_notes_history(
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the recent journal notes for the user."""
    notes = db.query(JournalNote).filter(
        JournalNote.user_id == user.id,
        JournalNote.content != ""
    ).order_by(JournalNote.date.desc()).limit(limit).all()
    
    return notes


@router.post("/notes", response_model=JournalNoteResponse)
async def save_note(
    data: JournalNoteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update a journal note for a specific date."""
    note = db.query(JournalNote).filter(
        JournalNote.user_id == user.id,
        JournalNote.date == data.date
    ).first()

    if note:
        note.content = data.content
    else:
        note = JournalNote(
            user_id=user.id,
            date=data.date,
            content=data.content
        )
        db.add(note)
        
    db.commit()
    db.refresh(note)
    return note



# ── Forward Benchmark: agent vs baselines ─────────────────────────────
#
# Reads the lookahead-free comparison accumulated by
# api/services/forward_benchmark.py. Lives under /journal because it is
# performance review, not live trading state.

@router.get("/benchmark")
async def get_forward_benchmark(
    ticker: Optional[str] = Query(None, description="Restrict to one ticker"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare the agent stack against deterministic baselines, measured forward.

    Every strategy was recorded at the same instant, entry price, horizon
    and cost — and none could see the outcome, so unlike a historical
    backtest of an LLM this is free of pretraining lookahead.
    """
    from api.services.forward_benchmark import build_comparison, format_comparison_report

    comparison = build_comparison(db, user.id, ticker=ticker)
    comparison["report_markdown"] = format_comparison_report(comparison)
    return comparison
