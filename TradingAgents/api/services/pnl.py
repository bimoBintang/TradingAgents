"""Real-time Daily P&L.

`PortfolioState.daily_pnl` (as historically written by `db_sync.save_graph_to_db`)
comes from `PortfolioManager.daily_pnl`, defined as
`total_equity - daily_starting_equity`. `daily_starting_equity` is set once
when the `PortfolioManager` object is constructed and is never reset — on a
long-running server this silently drifts into meaning "P&L since the process
last restarted," not "P&L today."

`compute_daily_pnl()` replaces that with a fresh, real-time computation off
actual trade timestamps: today's realized P&L (closed trades) plus current
unrealized P&L (open positions) — the same simplified convention most retail
platforms use for a "Daily P&L" tile. It has no persistent baseline to go
stale, so it's correct on every read regardless of uptime.
"""

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models import Trade


def compute_daily_pnl(db: Session, portfolio_id: int, positions: Iterable) -> float:
    """Today's realized P&L (UTC calendar day) + current unrealized P&L
    of all open positions.

    Args:
        db: Active DB session.
        portfolio_id: PortfolioState.id to scope the trade query to.
        positions: Already-fetched Position rows for this portfolio
            (avoids a second query — callers already have these).
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    realized_today = (
        db.query(func.coalesce(func.sum(Trade.realized_pnl), 0.0))
        .filter(
            Trade.portfolio_id == portfolio_id,
            Trade.fill_time >= today_start,
        )
        .scalar()
        or 0.0
    )

    unrealized = sum((p.unrealized_pnl or 0.0) for p in positions)

    return float(realized_today) + float(unrealized)
