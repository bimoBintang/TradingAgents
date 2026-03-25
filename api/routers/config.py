"""Config endpoints — read and update runtime configuration."""

import os
import json
import logging
from pathlib import Path
from fastapi import APIRouter, Depends

from api.schemas import ConfigResponse, ConfigUpdateRequest
from api.dependencies import get_config, CONFIG_PATH
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger("api.routers.config")
router = APIRouter(prefix="/api", tags=["Config"])

SENSITIVE_KEYS = {"api_key", "api_secret", "password", "telegram_bot_token"}

def filter_secrets(d: dict) -> dict:
    """Recursively remove sensitive keys before writing to disk."""
    import copy
    result = copy.deepcopy(d)
    for key, value in list(result.items()):
        if key in SENSITIVE_KEYS:
            del result[key]
        elif isinstance(value, dict):
            result[key] = filter_secrets(value)
    return result

@router.get("/config", response_model=ConfigResponse)
async def read_config(config=Depends(get_config)):
    """Return the current runtime config (sanitised — secrets masked)."""
    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.put("/config", response_model=ConfigResponse)
async def update_config(body: ConfigUpdateRequest, config=Depends(get_config)):
    """Merge partial updates into the live config and persist to disk.
    
    Uses an atomic file write to prevent corruption.
    """
    for key, value in body.updates.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value

    # Persist securely and atomically
    try:
        data_dir = CONFIG_PATH.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        
        safe_to_save = filter_secrets(config)
        tmp_path = data_dir / "agent_config.tmp.json"
        
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(safe_to_save, f, indent=2)
            
        os.replace(tmp_path, CONFIG_PATH)
    except OSError as e:
        logger.error("Failed to persist config to disk: %s", e)
        # We don't fail the request if persistent write fails, since memory is updated.

    safe = _sanitise(config)
    return ConfigResponse(config=safe)


@router.delete("/config/reset", response_model=ConfigResponse)
async def reset_config(config=Depends(get_config)):
    """Delete the persistent config and restore factory defaults in-memory."""
    import copy
    
    # 1. Reset memory config
    config.clear()
    config.update(copy.deepcopy(DEFAULT_CONFIG))
    
    # 2. Delete file
    try:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
    except OSError as e:
        logger.error("Failed to delete config file: %s", e)
        
    safe = _sanitise(config)
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
