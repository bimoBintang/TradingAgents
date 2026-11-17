"""Server-side software exits (trailing / ATR / max-hold) for live users.

The API builds a short-lived graph per request, so StopLossManager never lived
long enough to act. This job keeps one StopLossManager per user for the life of
the process and closes positions through the broker when it signals.

PnL is NOT booked here: once the position is gone, the next balance_sync cycle
sees it vanish and calls record_external_close (one path, no double count).

shortcut: watermarks and entry_time live in memory only. After a restart the
trailing stop restarts from entry price and max_hold counts from the first time
this process saw the position. Persist them if that matters.
"""

import logging
from datetime import datetime
from typing import Dict

from api.database import SessionLocal
from api.models import User
from api.services.balance_sync import _has_live_credentials
from api.user_context import get_user_config
from tradingagents.execution.order_models import OrderSide, OrderType
from tradingagents.execution.stop_loss_manager import StopLossManager

logger = logging.getLogger("api.services.exit_monitor")

_managers: Dict[int, StopLossManager] = {}


def monitor_user_exits(user_id: int) -> int:
    """One monitoring pass for a user. Returns the number of exits executed."""
    with SessionLocal() as db:
        cfg = get_user_config(db, user_id)
    exec_cfg = cfg.get("execution", {})
    if not _has_live_credentials(exec_cfg):
        return 0

    from tradingagents.graph.trading_graph import _create_broker

    broker = _create_broker({"execution": exec_cfg, "portfolio": {"initial_cash": 10000.0}})
    if exec_cfg.get("market_type") == "future" and hasattr(broker, "get_futures_positions"):
        positions = broker.get_futures_positions()
    else:
        positions = broker.get_positions()

    risk = cfg.get("risk_controls", {})
    mgr = _managers.setdefault(user_id, StopLossManager(
        trailing_stop_pct=risk.get("trailing_stop_pct", 0.05),
        atr_multiplier=risk.get("atr_multiplier", 2.0),
        max_hold_hours=risk.get("max_hold_hours", 72),
    ))

    by_ticker = {p.ticker: p for p in positions}
    for t in list(mgr._positions):
        if t not in by_ticker:
            mgr.unregister_position(t)
    for t, p in by_ticker.items():
        if t not in mgr._positions:
            p.entry_timestamp = datetime.utcnow()  # see shortcut above
            mgr.register_position(p)

    prices = {t: p.current_price for t, p in by_ticker.items() if p.current_price}
    done = 0
    for sig in mgr.check_exits(prices):
        pos = by_ticker.get(sig.ticker)
        if pos is None:
            continue
        close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
        try:
            result = broker.place_order(
                ticker=sig.ticker, side=close_side, quantity=pos.quantity, order_type=OrderType.MARKET,
            )
            if result and (result.is_filled or result.is_partial):
                broker.cancel_protective_stops(sig.ticker)
                mgr.unregister_position(sig.ticker)
                done += 1
                logger.warning("User %d: software exit %s (%s)", user_id, sig.ticker, sig.reason.value)
        except Exception as e:
            logger.error("User %d: exit order for %s failed: %s", user_id, sig.ticker, e)
    return done


def monitor_all_live_users() -> None:
    """Run one pass for every user; one user's failure never stops the rest."""
    with SessionLocal() as db:
        user_ids = [uid for (uid,) in db.query(User.id).all()]
    for uid in user_ids:
        try:
            monitor_user_exits(uid)
        except Exception as e:
            logger.error("Exit monitor failed for user %d: %s", uid, e)
