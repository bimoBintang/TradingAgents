"""Shared dependencies — singleton TradingAgentsGraph instance.

The graph is initialised once during FastAPI's lifespan and injected
into route handlers via `Depends(get_graph)`.
"""

import os
import time
import logging
from collections import defaultdict
from typing import Dict, Any, Optional

from dotenv import load_dotenv

import json
from pathlib import Path
from tradingagents.default_config import DEFAULT_CONFIG

load_dotenv()

logger = logging.getLogger("api.dependencies")

# ── Persistent Config Paths ───────────────────────────────────────────
CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "agent_config.json"

# ── Module-level singletons ───────────────────────────────────────────

_graph = None
_config: Dict[str, Any] = {}
_start_time: float = 0.0
_init_error: Optional[str] = None

# Background analysis results store  {user_id: {task_id: {...}}}
_analysis_results: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dictionary into base dictionary."""
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_user_analysis_results(user_id: int) -> Dict[str, Dict[str, Any]]:
    """Get the analysis results dict scoped to a specific user."""
    return _analysis_results[user_id]


def init_graph(config: Optional[Dict[str, Any]] = None):
    """Initialise a TradingAgentsGraph and return it.

    If *config* is provided (per-user), creates a NEW non-singleton graph
    for that specific user's analysis task.

    If *config* is None, returns the global singleton graph (created on
    first call with DEFAULT_CONFIG for health-check / status endpoints).
    """
    global _graph, _config, _start_time, _init_error

    # ── Per-user graph (non-singleton) ────────────────────────────────
    if config is not None:
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            user_graph = TradingAgentsGraph(debug=False, config=config)
            logger.info("Created per-user graph — session %s", user_graph.session_id)
            return user_graph
        except Exception as e:
            logger.error("Per-user graph init failed: %s", e)
            raise

    # ── Global singleton (startup / health-check) ─────────────────────
    if _graph is not None:
        return _graph

    startup_config = DEFAULT_CONFIG.copy()

    # In Multi-Tenant SaaS, the global singleton graph shouldn't load single-user API keys
    # from the legacy local JSON file. It should use the clean DEFAULT_CONFIG.
    # Per-user configurations are dynamically loaded from DB during task execution instead.
    
    # Allow env-var overrides for common settings
    if os.getenv("EXECUTION_MODE"):
        startup_config.setdefault("execution", {})["mode"] = os.getenv("EXECUTION_MODE")
    if os.getenv("EXECUTION_BROKER"):
        startup_config.setdefault("execution", {})["broker"] = os.getenv("EXECUTION_BROKER")

    _config = startup_config
    _start_time = time.time()

    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        _graph = TradingAgentsGraph(debug=False, config=startup_config)
        
        try:
            from api.db_sync import load_graph_from_db
            load_graph_from_db(_graph)
        except Exception as db_e:
            logger.error("Failed to load graph from DB: %s", db_e)
            
        logger.info("Graph ready — session %s", _graph.session_id)
    except Exception as e:
        _init_error = str(e)
        logger.warning("Graph init failed: %s. Server running in degraded mode.", e)
        _graph = None

    return _graph


def get_graph():
    """FastAPI dependency — returns the singleton graph.

    Raises HTTPException 503 if the graph failed to initialise.
    """
    if _graph is None:
        from fastapi import HTTPException
        detail = f"TradingAgentsGraph not available. {_init_error or 'Check OPENAI_API_KEY and .env file.'}"
        raise HTTPException(status_code=503, detail=detail)
    return _graph


def get_graph_optional():
    """Returns the graph or None (no exception)."""
    return _graph


def get_config() -> Dict[str, Any]:
    """Return the live config dict (mutable reference)."""
    return _config


def get_uptime() -> float:
    """Seconds since server start."""
    return time.time() - _start_time


def get_init_error() -> Optional[str]:
    """Return the init error message, if any."""
    return _init_error
