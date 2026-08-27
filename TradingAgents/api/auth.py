"""Authentication utilities — JWT tokens, Clerk verification, and DB users.
Uses the SQL database via Clerk identity mapping.
"""
import os
import logging
import urllib.request
import json
from datetime import datetime
from functools import lru_cache
from typing import Optional

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import User

logger = logging.getLogger("api.auth")

CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "https://unbiased-marten-28.clerk.accounts.dev/.well-known/jwks.json")

@lru_cache(maxsize=1)
def get_clerk_jwks():
    try:
        req = urllib.request.Request(CLERK_JWKS_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        return {"keys": []}

def get_user_by_clerk_id(db: Session, clerk_id: str) -> Optional[User]:
    return db.query(User).filter(User.clerk_id == clerk_id).first()


class ClerkTokenInvalid(Exception):
    """A Clerk bearer token failed verification (bad signature, missing kid, etc.)."""


def verify_clerk_jwt(token: str) -> str:
    """Verify a Clerk-issued JWT and return its `sub` (Clerk user id).

    Pure verification only — no DB access, no FastAPI dependencies — so
    it can be reused by both the REST API (get_current_user, below) and
    the MCP server's HTTP transport (mcp_server/auth.py), which has no
    FastAPI Request to depend on.

    Raises ClerkTokenInvalid on any failure.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise ClerkTokenInvalid("Token header missing 'kid'")

        jwks = get_clerk_jwks()
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key["kid"] == kid:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
                break

        if not rsa_key:
            raise ClerkTokenInvalid(f"No matching JWKS key for kid={kid}")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            options={"verify_aud": False} # Skip checking audience explicitly for now
        )
        clerk_id: str = payload.get("sub")
        if not clerk_id:
            raise ClerkTokenInvalid("Token payload missing 'sub'")
        return clerk_id

    except JWTError as e:
        raise ClerkTokenInvalid(str(e)) from e


def get_or_create_user_by_clerk_id(db: Session, clerk_id: str) -> User:
    """Look up the User for a verified Clerk id, auto-creating one on first sight.

    Shared by get_current_user (REST) and the MCP server's HTTP auth
    (mcp_server/auth.py) so both paths create/resolve accounts identically.
    """
    user = get_user_by_clerk_id(db, clerk_id)
    if not user:
        # Create user mapping to clerk sub
        user = User(
            email=f"{clerk_id}@clerk.local",
            clerk_id=clerk_id,
            name="Clerk Identity",
            hashed_password="clerk_external_auth",
            is_admin=True # Set first incoming user to Admin for ease of development migration
        )
        db.add(user)
        db.flush()  # Flush so user.id is available for FK relations

        # Auto-create default UserConfig (multi-tenant isolation)
        from api.user_context import ensure_user_config, ensure_portfolio
        ensure_user_config(db, user)

        # Auto-create default portfolio for new user
        ensure_portfolio(db, user)

        db.commit()  # Single atomic commit: User + UserConfig + Portfolio
        db.refresh(user)

    return user


async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Extract and validate the JWT from the Clerk Authorized Bearer token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session from Clerk",
    )

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise credentials_exception

    token = auth_header.split(" ")[1]

    try:
        clerk_id = verify_clerk_jwt(token)
    except ClerkTokenInvalid as e:
        logger.error(f"JWT Validation failed: {e}")
        raise credentials_exception

    return get_or_create_user_by_clerk_id(db, clerk_id)

async def get_current_admin_user(
    user: User = Depends(get_current_user),
) -> User:
    """Require the authenticated user to have admin privileges."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
