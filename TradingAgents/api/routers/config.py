"""Config endpoints — read and update runtime configuration (per-user).

Multi-tenant: each user's config is stored in the `user_configs` table.
API credentials are encrypted via Fernet and never stored in config_json.
"""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas import ConfigResponse, ConfigUpdateRequest
from api.auth import get_current_user
from api.database import get_db
from api.models import User
from api.user_context import get_user_config, save_user_config
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger("api.routers.config")
router = APIRouter(prefix="/api", tags=["Config"])

SENSITIVE_KEYS = {"api_key", "api_secret", "password", "telegram_bot_token"}


@router.get("/config", response_model=ConfigResponse)
async def read_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's runtime config (secrets masked)."""
    config = get_user_config(db, user.id)
    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.put("/config", response_model=ConfigResponse)
async def update_config(
    body: ConfigUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Merge partial updates into the user's config and persist to DB.

    Credentials are encrypted before storage. Other fields are
    deep-merged into the existing config_json.
    """
    save_user_config(db, user.id, body.updates)

    # Return updated config
    config = get_user_config(db, user.id)
    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.delete("/config/reset", response_model=ConfigResponse)
async def reset_config(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset the user's config to factory defaults."""
    import copy
    from api.models import UserConfig

    uc = db.query(UserConfig).filter(UserConfig.user_id == user.id).first()
    if uc:
        uc.config_json = "{}"
        uc.encrypted_api_key = ""
        uc.encrypted_api_secret = ""
        uc.encrypted_password = ""
        db.commit()

    safe = _sanitise(copy.deepcopy(DEFAULT_CONFIG))
    return ConfigResponse(config=safe)


def _sanitise(config: dict) -> dict:
    """Mask sensitive fields before returning to clients."""
    import copy

    safe = copy.deepcopy(config)

    # Mask API secrets
    for section_key in ("execution", "notifications"):
        section = safe.get(section_key, {})
        for secret_key in SENSITIVE_KEYS:
            if section.get(secret_key):
                section[secret_key] = "****" + section[secret_key][-4:] if len(section[secret_key]) > 4 else "****"

    return safe
