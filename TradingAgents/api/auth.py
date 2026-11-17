"""Single-owner identity.

This deployment is personal: there is no login. Every request acts as the one
owner row in `users` (the first row if data already exists, otherwise a new
`owner@local`). The API has NO authentication, so keep port 8000 unreachable
from untrusted networks (localhost / VPN / firewall).
"""

import logging

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import User

logger = logging.getLogger("api.auth")

OWNER_EMAIL = "owner@local"


def get_or_create_owner(db: Session) -> User:
    """Return the owner: the first user row, created with default config/portfolio if absent."""
    user = db.query(User).order_by(User.id.asc()).first()
    if user:
        return user

    user = User(email=OWNER_EMAIL, name="Owner", hashed_password="")
    db.add(user)
    db.flush()  # user.id for the FKs below

    from api.user_context import ensure_user_config, ensure_portfolio
    ensure_user_config(db, user)
    ensure_portfolio(db, user)
    db.commit()
    db.refresh(user)
    return user


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: always the owner. Name kept so routers and test overrides stay valid."""
    user = get_or_create_owner(db)
    request.state.user_id = user.id  # the rate limiter keys on this (api/limiter.py)
    return user
