"""Per-user context — FastAPI dependencies for tenant-scoped data access.

Provides `get_user_portfolio()` which loads or creates the authenticated
user's portfolio from the database.  Used by portfolio, journal, and
analysis routers to enforce data isolation.

Also provides `get_user_config()` and `save_user_config()` for per-user
configuration isolation (multi-tenant SaaS).
"""

import copy
import json
import logging
from typing import Optional, Dict, Any, List

from fastapi import Depends
from sqlalchemy.orm import Session

from api.database import get_db
from api.auth import get_current_user
from api.models import User, UserConfig, PortfolioState, Position, Trade
from api.crypto import encrypt, decrypt
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger("api.user_context")

CURRENT_CONFIG_VERSION = 1


# ── Deep Merge Utility ────────────────────────────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a deep copy of *base*.

    - Dict values are merged recursively.
    - All other types in *override* replace the base value.
    """
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# ── Per-User Config I/O ───────────────────────────────────────────────

def get_user_config(db: Session, user_id: int) -> dict:
    """Load the full runtime config for *user_id*.

    1. Reads the user's `UserConfig` row from the database.
    2. Deep-merges the stored JSON overrides on top of DEFAULT_CONFIG
       so new fields are always present (forward-compatible).
    3. Decrypts API credentials and injects them into the returned dict.

    If the user has no UserConfig row yet, returns a pristine copy of
    DEFAULT_CONFIG.
    """
    uc = db.query(UserConfig).filter(UserConfig.user_id == user_id).first()
    if not uc:
        return copy.deepcopy(DEFAULT_CONFIG)

    user_overrides = json.loads(uc.config_json) if uc.config_json else {}
    merged = deep_merge(DEFAULT_CONFIG, user_overrides)

    # Inject decrypted credentials into the execution block
    exec_block = merged.setdefault("execution", {})
    if uc.encrypted_api_key:
        exec_block["api_key"] = decrypt(uc.encrypted_api_key)
    if uc.encrypted_api_secret:
        exec_block["api_secret"] = decrypt(uc.encrypted_api_secret)
    if uc.encrypted_password:
        exec_block["password"] = decrypt(uc.encrypted_password)

    # ── Auto-upgrade: paper → live jika user sudah punya API key ──
    has_api_key = bool(exec_block.get("api_key"))
    has_api_secret = bool(exec_block.get("api_secret"))
    has_exchange = bool(exec_block.get("exchange"))

    if has_api_key and has_api_secret and has_exchange:
        # User sudah mengisi kredensial → upgrade ke live
        if exec_block.get("broker") == "paper":
            exec_block["broker"] = "ccxt"
            logger.info("Auto-upgrade user %d to CCXT live (%s)", user_id, exec_block.get("exchange"))
        if exec_block.get("mode") == "paper":
            exec_block["mode"] = "live"
    else:
        # Belum ada key → pastikan tetap paper (safety net)
        exec_block["broker"] = "paper"
        exec_block["mode"] = "paper"

    return merged


def save_user_config(db: Session, user_id: int, updates: dict) -> None:
    """Persist partial config updates for *user_id*.

    - Credentials (api_key, api_secret, password) are extracted,
      encrypted via Fernet, and stored in dedicated columns.
    - Remaining fields are deep-merged into the existing config_json.
    - config_version is bumped to CURRENT_CONFIG_VERSION.
    """
    uc = db.query(UserConfig).filter(UserConfig.user_id == user_id).first()
    if not uc:
        uc = UserConfig(user_id=user_id)
        db.add(uc)

    # ── Extract and encrypt credentials ───────────────────────────────
    exec_updates = updates.get("execution", {})
    if isinstance(exec_updates, dict):
        if "api_key" in exec_updates:
            raw = exec_updates.pop("api_key")
            if raw and raw != "****" and not raw.startswith("****"):
                uc.encrypted_api_key = encrypt(raw)
        if "api_secret" in exec_updates:
            raw = exec_updates.pop("api_secret")
            if raw and raw != "****" and not raw.startswith("****"):
                uc.encrypted_api_secret = encrypt(raw)
        if "password" in exec_updates:
            raw = exec_updates.pop("password")
            if raw and raw != "****" and not raw.startswith("****"):
                uc.encrypted_password = encrypt(raw)

    # ── Deep merge remaining fields ───────────────────────────────────
    existing = json.loads(uc.config_json) if uc.config_json else {}
    merged = deep_merge(existing, updates)
    uc.config_json = json.dumps(merged)
    uc.config_version = CURRENT_CONFIG_VERSION

    db.commit()
    db.refresh(uc)


def ensure_user_config(db: Session, user: User) -> UserConfig:
    """Get or create a UserConfig row for *user*."""
    uc = db.query(UserConfig).filter(UserConfig.user_id == user.id).first()
    if not uc:
        uc = UserConfig(user_id=user.id, config_json="{}", config_version=CURRENT_CONFIG_VERSION)
        db.add(uc)
        db.commit()
        db.refresh(uc)
        logger.info("Created default UserConfig for user %s (id=%d)", user.email, user.id)
    return uc


# ── Portfolio Helpers (existing) ──────────────────────────────────────

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

