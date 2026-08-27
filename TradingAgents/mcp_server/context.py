"""Per-user context for MCP tools.

Mirrors `api/user_context.py`'s job of resolving "which User is this
request for", but the MCP server has two very different deployment
shapes to support:

  Local (stdio, the default — Claude Desktop/Code on your own
  machine): there's no HTTP request/Authorization header to verify,
  so identity is fixed once per process instead, resolved in priority
  order from:

    1. agent_config.json's `mcp.user_email` — settable in the
       dashboard under Settings > MCP Server (same persistence as
       every other runtime setting, via PUT /api/config).
    2. TRADINGAGENTS_MCP_USER_EMAIL in .env — power-user/ops override,
       doesn't require the dashboard to be running.
    3. The first user in the DB, with a warning logged.

    This is a single-user-per-process model — an LLM should not be
    trusted to select whose portfolio to read/trade on a per-call
    basis, so tools deliberately never accept a user/email argument.

  Remote (streamable-http, opt-in via MCP_TRANSPORT — see server.py
  and mcp_server/auth.py): each request carries its own verified
  Clerk bearer token, so identity is resolved PER REQUEST from that
  token instead — this takes priority over the config-based fallback
  above, since a real authenticated caller is always more correct
  than a guessed default.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.dependencies import CONFIG_PATH
from api.models import User

logger = logging.getLogger("mcp_server.context")


def _authenticated_clerk_id() -> Optional[str]:
    """Return the verified Clerk id for the current request, if any.

    Only ever non-None under the streamable-http transport with
    mcp_server/auth.py's ClerkTokenVerifier wired in — stdio requests
    have no bearer token, so this is always None there and
    resolve_mcp_user() falls through to the config-based lookup.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:  # pragma: no cover - auth extra not installed
        return None

    token = get_access_token()
    return token.subject if token else None


def _configured_email() -> Optional[str]:
    """Read mcp.user_email from agent_config.json, if set."""
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        email = (saved.get("mcp") or {}).get("user_email")
        return email or None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read %s: %s", CONFIG_PATH, e)
        return None


class McpUserNotConfigured(RuntimeError):
    """Raised when the MCP server can't determine which user it's acting as."""


@contextmanager
def db_session() -> Iterator[Session]:
    """Open a DB session for one tool call and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def resolve_mcp_user(db: Session) -> User:
    """Resolve which User this MCP server process (or, in HTTP mode,
    this specific request) acts as.

    See module docstring for the full resolution order.
    """
    clerk_id = _authenticated_clerk_id()
    if clerk_id:
        from api.auth import get_or_create_user_by_clerk_id
        return get_or_create_user_by_clerk_id(db, clerk_id)

    email = _configured_email() or os.getenv("TRADINGAGENTS_MCP_USER_EMAIL")

    if email:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise McpUserNotConfigured(
                f"Configured MCP user email {email!r} does not match any "
                "user in the database. Check Settings > MCP Server in the "
                "dashboard (or TRADINGAGENTS_MCP_USER_EMAIL in .env)."
            )
        return user

    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise McpUserNotConfigured(
            "No users exist in the database yet, and no MCP user email is "
            "configured. Sign up via the dashboard first, then set it under "
            "Settings > MCP Server."
        )
    logger.warning(
        "No MCP user email configured (Settings > MCP Server, or "
        "TRADINGAGENTS_MCP_USER_EMAIL) — defaulting to first user in DB "
        "(%s). Set it explicitly to avoid ambiguity.",
        user.email,
    )
    return user
