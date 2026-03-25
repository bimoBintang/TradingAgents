"""Per-user context — FastAPI dependencies for tenant-scoped data access.

Provides `get_user_portfolio()` which loads or creates the authenticated
user's portfolio from the database.  Used by portfolio, journal, and
analysis routers to enforce data isolation.
"""

import logging
from typing import Optional, Dict, Any, List

from fastapi import Depends
from sqlalchemy.orm import Session

from api.database import get_db
from api.auth import get_current_user
from api.models import User, PortfolioState, Position, Trade

logger = logging.getLogger("api.user_context")


def ensure_portfolio(db: Session, user: User) -> PortfolioState:
    """Get or create a PortfolioState for the given user."""
    ps = db.query(PortfolioState).filter(PortfolioState.user_id == user.id).first()
    if not ps:
        ps = PortfolioState(user_id=user.id)
        db.add(ps)
        db.commit()
        db.refresh(ps)
        logger.info("Created default portfolio for user %s (id=%d)", user.email, user.id)
    return ps


def get_user_portfolio(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """FastAPI dependency — returns the authenticated user's portfolio context.

    Returns dict with:
        user: User model
        portfolio: PortfolioState model
        positions: list of Position models
        trades: list of Trade models
        db: active DB session
    """
    ps = ensure_portfolio(db, user)
    positions = db.query(Position).filter(Position.portfolio_id == ps.id).all()
    trades = (
        db.query(Trade)
        .filter(Trade.portfolio_id == ps.id)
        .order_by(Trade.fill_time.desc())
        .all()
    )

    return {
        "user": user,
        "portfolio": ps,
        "positions": positions,
        "trades": trades,
        "db": db,
    }
