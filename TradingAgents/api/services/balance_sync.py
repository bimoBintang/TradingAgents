"""Periodic real-broker balance/position sync.

`PortfolioManager` keeps its own internal ledger — `cash_balance` and
`positions` computed purely from the bot's own recorded trades. For a real
(non-paper) broker, this drifts from the exchange's actual balance over time
(fees, funding payments, manual/external trades, rounding) with nothing to
correct it: `TradingAgentsGraph` only ever reconciles once, at construction
(`execution_engine.reconcile()`), and per-user graphs in this SaaS are
short-lived, request-scoped objects (see `api/dependencies.py::init_graph`)
that don't stick around to be reconciled again later.

`sync_user_balance()` closes that gap. It builds a throwaway broker exactly
like `POST /api/config/test-broker` does, pulls the REAL balance and
positions, and writes them straight into this user's `PortfolioState` /
`Position` rows — the same rows `/ws/portfolio` already streams to the
dashboard every 5 seconds. No changes needed on the read side: once this
keeps the DB row fresh, the existing WebSocket push becomes accurate for
free.

Called two ways:
  1. Periodically, for every user, by the APScheduler job registered in
     `api/main.py`'s lifespan (`sync_all_live_users`).
  2. Synchronously, right after a live trade fills, from `api/tasks.py`.

Deliberately synchronous throughout (ccxt/alpaca calls are blocking network
I/O regardless of async/await) — the scheduler wraps it in a threadpool,
`api/tasks.py` already runs in its own worker thread.
"""

import logging
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.models import EquityCurvePoint, PortfolioState, Position, User
from api.user_context import get_user_config
from tradingagents.execution.brokers.broker_base import BrokerConnectionError

logger = logging.getLogger("api.services.balance_sync")


def _has_live_credentials(exec_cfg: dict) -> bool:
    """Mirrors the auto-upgrade condition in `api/user_context.py` and the
    Settings page's live-trading confirmation gate EXACTLY: broker isn't
    paper, and exchange/api_key/api_secret are all present. If that
    condition wouldn't put the account in live mode, there's no real
    account here to sync against.
    """
    if exec_cfg.get("broker") == "mt5":
        from tradingagents.execution.brokers.mt5_broker import mt5_env_configured
        return mt5_env_configured()
    return (
        exec_cfg.get("broker") != "paper"
        and bool(exec_cfg.get("exchange"))
        and bool(exec_cfg.get("api_key"))
        and bool(exec_cfg.get("api_secret"))
    )


def record_external_close(user_id: int, cfg: dict, ticker: str, side: str,
                          quantity: float, entry_price: float, last_price: float) -> None:
    """Book a position that vanished from the exchange (venue stop / liquidation).

    Without this the loss never reaches RiskController's loss streak or drawdown
    window, because the sync below overwrites the stored positions. Exit price is
    the last stored price, so the PnL is an estimate. Never raises.
    """
    try:
        from tradingagents.execution.risk_controls import RiskController
        from tradingagents.storage.database import Database

        storage = cfg.get("storage", {})
        if not storage.get("enabled", False):
            return
        risk_cfg = cfg.get("risk_controls", {})
        rc = RiskController(
            db=Database(storage.get("db_path", "~/.tradingagents/trading.db")),
            account_id=storage.get("account_id", f"user_{user_id}"),
            consecutive_loss_limit=risk_cfg.get("consecutive_loss_limit", 3),
            consecutive_loss_cooldown_seconds=risk_cfg.get("cooldown_seconds", 1800),
        )
        pnl = (last_price - entry_price) * quantity
        if side != "BUY":
            pnl = -pnl
        rc.record_trade_result(pnl, ticker)
        logger.warning("User %d: %s closed outside the engine (est. PnL %.2f) — recorded.", user_id, ticker, pnl)
    except Exception as e:
        logger.error("Could not record external close of %s for user %d: %s", ticker, user_id, e)


def sync_user_balance(user_id: int, db: Optional[Session] = None) -> bool:
    """Pull real balance + positions from this user's broker and persist them.

    Returns:
        True if a sync was attempted and succeeded.
        False if skipped (paper broker / incomplete credentials) or failed
        (logged, never raised — one user's broker outage must never break
        a batch sync covering many users).
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        exec_cfg = get_user_config(db, user_id).get("execution", {})
        if not _has_live_credentials(exec_cfg):
            return False

        # Local import: avoids pulling the full TradingAgentsGraph module
        # (heavy, LLM-client-loading) into every import of this module.
        from tradingagents.graph.trading_graph import _create_broker

        broker = _create_broker({
            "execution": exec_cfg,
            "portfolio": {"initial_cash": 10000.0},
        })

        # fetch_balance_strict(), not get_balance(): the latter swallows
        # every error (bad key, network blip) into a zeroed fallback dict,
        # which would silently zero out a real account's balance here.
        balance = broker.fetch_balance_strict()
        cash = float(balance.get("cash", 0.0) or 0.0)
        equity = float(balance.get("total_equity", cash) or cash)

        if exec_cfg.get("market_type") == "future" and hasattr(broker, "get_futures_positions"):
            positions = broker.get_futures_positions()
        else:
            positions = broker.get_positions()

        ps = db.query(PortfolioState).filter(PortfolioState.user_id == user_id).first()
        if not ps:
            ps = PortfolioState(user_id=user_id)
            db.add(ps)
            db.flush()

        ps.cash_balance = cash
        ps.total_equity = equity

        # Broker positions are the ground truth now — clear and reinsert,
        # same pattern api/db_sync.py::save_graph_to_db already uses.
        live_tickers = {p.ticker for p in positions}
        for old in db.query(Position).filter(Position.portfolio_id == ps.id).all():
            if old.ticker not in live_tickers:
                record_external_close(
                    user_id, get_user_config(db, user_id), old.ticker, old.side,
                    old.quantity, old.entry_price, old.current_price,
                )
        db.query(Position).filter(Position.portfolio_id == ps.id).delete()
        for p in positions:
            db.add(Position(
                portfolio_id=ps.id,
                ticker=p.ticker,
                side=p.side.value if hasattr(p.side, "value") else str(p.side),
                quantity=p.quantity,
                entry_price=p.entry_price,
                current_price=p.current_price,
                unrealized_pnl=getattr(p, "unrealized_pnl", 0.0) or 0.0,
            ))

        # Real, restart-proof max drawdown: historical peak from the
        # equity_curve_points table (this row included), not
        # PortfolioManager.peak_equity (reset to current equity on every
        # restart — see api/db_sync.py::load_graph_from_db).
        db.add(EquityCurvePoint(user_id=user_id, equity=equity))
        historical_max = db.query(func.max(EquityCurvePoint.equity)).filter(
            EquityCurvePoint.user_id == user_id
        ).scalar() or equity
        historical_max = max(historical_max, equity)
        ps.max_drawdown_pct = (
            max(0.0, (historical_max - equity) / historical_max)
            if historical_max > 0 else 0.0
        )

        db.commit()
        logger.info(
            "Synced real balance for user %d: cash=$%.2f equity=$%.2f positions=%d drawdown=%.1f%%",
            user_id, cash, equity, len(positions), ps.max_drawdown_pct * 100,
        )
        return True

    except BrokerConnectionError as e:
        logger.warning("Balance sync skipped for user %d: broker unreachable: %s", user_id, e)
        db.rollback()
        return False
    except Exception as e:
        logger.error("Balance sync failed for user %d: %s", user_id, e)
        db.rollback()
        return False
    finally:
        if owns_session:
            db.close()


def sync_all_live_users() -> None:
    """Sync every user who has a live broker configured. Isolated per-user
    (via sync_user_balance's own try/except) — one broker outage never
    stops the rest of the batch. Called on a timer — see api/main.py.
    """
    with SessionLocal() as db:
        user_ids = [uid for (uid,) in db.query(User.id).all()]

    synced = 0
    for uid in user_ids:
        if sync_user_balance(uid):
            synced += 1
    if synced:
        logger.info("Balance sync cycle complete: %d/%d users synced", synced, len(user_ids))
