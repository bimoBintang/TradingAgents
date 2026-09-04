"""Synchronize TradingAgentsGraph state with the SQL database.

Supports per-user (multi-tenant) isolation via user_id parameter.
Falls back to global (first row) if user_id is not provided.

IMPORTANT: PortfolioManager uses @property for computed fields like
total_equity, win_rate, daily_pnl, max_drawdown_pct, total_trades.
These are READ-ONLY and derived from cash_balance + positions + trade_history.
We must NOT try to set them — instead we restore the raw data they compute from.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session
from api.database import SessionLocal
from api.models import EquityCurvePoint, PortfolioState, Position, Trade

logger = logging.getLogger("api.db_sync")


def _get_portfolio_state(db: Session, user_id: Optional[int] = None) -> Optional[PortfolioState]:
    """Get PortfolioState by user_id, or fallback to first row."""
    if user_id is not None:
        return db.query(PortfolioState).filter(PortfolioState.user_id == user_id).first()
    return db.query(PortfolioState).first()


def load_graph_from_db(graph, user_id: Optional[int] = None):
    """Load Portfolio and Journal state from the database into memory.

    Args:
        graph: TradingAgentsGraph instance
        user_id: If provided, load only this user's data (multi-tenant).
                 If None, load the first portfolio (legacy single-tenant).
    """
    with SessionLocal() as db:
        ps_model = _get_portfolio_state(db, user_id)
        if not ps_model:
            return  # Nothing to load

        # ── Restore primitive (writable) fields ──────────────────────
        graph.portfolio_manager.cash_balance = ps_model.cash_balance
        graph.portfolio_manager.total_pnl = ps_model.total_pnl
        # NOTE: total_equity, win_rate, daily_pnl, max_drawdown_pct,
        #       total_trades are all @property — they auto-compute.

        # ── Restore positions into the Dict[str, PositionInfo] ───────
        from tradingagents.execution.order_models import PositionInfo, OrderSide

        positions = db.query(Position).filter(
            Position.portfolio_id == ps_model.id
        ).all()

        graph.portfolio_manager.positions = {}
        for p in positions:
            graph.portfolio_manager.positions[p.ticker] = PositionInfo(
                ticker=p.ticker,
                side=OrderSide.BUY if p.side == "BUY" else OrderSide.SELL,
                quantity=p.quantity,
                entry_price=p.entry_price,
                current_price=p.current_price,
                entry_timestamp=datetime.utcnow(),
            )

        # ── Restore trades into trade_history ────────────────────────
        from tradingagents.execution.portfolio_manager import TradeRecord

        db_trades = db.query(Trade).filter(
            Trade.portfolio_id == ps_model.id
        ).order_by(Trade.fill_time.asc()).all()

        graph.portfolio_manager.trade_history = []
        for t in db_trades:
            graph.portfolio_manager.trade_history.append(
                TradeRecord(
                    ticker=t.ticker,
                    side=t.action,
                    entry_price=t.fill_price,
                    exit_price=t.fill_price,
                    quantity=t.filled_qty,
                    entry_time=t.fill_time or datetime.utcnow(),
                    exit_time=t.fill_time or datetime.utcnow(),
                    pnl=t.realized_pnl or 0.0,
                )
            )

        logger.info(
            "Loaded %d positions and %d trades from DB (user_id=%s).",
            len(positions), len(db_trades), user_id,
        )

        # Restore the REAL historical peak from equity_curve_points, not
        # today's equity — this used to unconditionally do
        # `peak_equity = total_equity`, which silently forgets any real
        # drawdown that happened before every single restart (a
        # long-running live bot could be sitting at -30% off its true
        # peak and this would report 0% right after a reboot). Falls
        # back to current equity only when there's no history yet.
        current_equity = graph.portfolio_manager.total_equity
        historical_max = None
        if user_id is not None:
            historical_max = db.query(func.max(EquityCurvePoint.equity)).filter(
                EquityCurvePoint.user_id == user_id
            ).scalar()
        graph.portfolio_manager.peak_equity = max(historical_max or current_equity, current_equity)


def save_graph_to_db(graph, user_id: Optional[int] = None):
    """Save Portfolio and Journal state to the database.

    Args:
        graph: TradingAgentsGraph instance
        user_id: If provided, save to this user's portfolio (multi-tenant).
                 If None, save to the first portfolio (legacy single-tenant).
    """
    with SessionLocal() as db:
        ps_model = _get_portfolio_state(db, user_id)
        if not ps_model:
            ps_model = PortfolioState(user_id=user_id)
            db.add(ps_model)
            db.commit()
            db.refresh(ps_model)

        # Write snapshot values from computed properties
        ps = graph.portfolio_manager.get_portfolio_state()
        ps_model.cash_balance = ps.cash_balance
        ps_model.total_equity = ps.total_equity
        ps_model.total_pnl = ps.total_pnl
        ps_model.daily_pnl = ps.daily_pnl
        ps_model.win_rate = ps.win_rate
        ps_model.max_drawdown_pct = ps.max_drawdown_pct
        ps_model.total_trades = ps.total_trades

        # Record a real, permanent equity snapshot — see load_graph_from_db's
        # peak_equity restoration above and api/services/balance_sync.py
        # (which appends the equivalent snapshot for live/broker-synced
        # accounts). This is the paper-account / analysis-tick side of the
        # same equity_curve_points history.
        if user_id is not None:
            db.add(EquityCurvePoint(user_id=user_id, equity=ps.total_equity))

        # Sync positions (clear + reinsert)
        db.query(Position).filter(Position.portfolio_id == ps_model.id).delete()
        for ticker, p in graph.portfolio_manager.positions.items():
            db.add(Position(
                portfolio_id=ps_model.id,
                ticker=p.ticker,
                side=p.side.value if hasattr(p.side, "value") else str(p.side),
                quantity=p.quantity,
                entry_price=p.entry_price,
                current_price=p.current_price,
                unrealized_pnl=p.unrealized_pnl,
            ))

        # Sync trades (clear + reinsert)
        db.query(Trade).filter(Trade.portfolio_id == ps_model.id).delete()
        for t in graph.portfolio_manager.trade_history:
            db.add(Trade(
                portfolio_id=ps_model.id,
                ticker=t.ticker,
                action=t.side,
                filled_qty=t.quantity,
                fill_price=t.exit_price,
                realized_pnl=t.pnl,
                status="FILLED",
                fill_time=t.exit_time,
            ))

        db.commit()
        logger.info("Synced graph state to DB (user_id=%s).", user_id)
