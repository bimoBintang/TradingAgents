"""Context for MCP tools: DB session helper and the acting user.

There is one owner (see api/auth.py), so every tool acts as the owner. Tools
deliberately never accept a user argument.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.models import User

logger = logging.getLogger("mcp_server.context")


class McpUserNotConfigured(RuntimeError):
    """Kept for callers that catch it; the owner is now always resolvable."""


@contextmanager
def db_session() -> Iterator[Session]:
    """Open a DB session for one tool call and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def resolve_mcp_user(db: Session) -> User:
    """The acting user: the single owner."""
    from api.auth import get_or_create_owner
    return get_or_create_owner(db)
