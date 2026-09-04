"""Unit tests for the agent runtime config persistence.

Two independent config stores exist in this codebase — tests below are
split accordingly:

1. The legacy global-singleton bootstrap (`api.dependencies.init_graph`),
   which still reads `agent_config.json` from disk — this is what
   `mock_config_path` + `clean_config` below exercise directly (no HTTP
   involved).
2. The multi-tenant per-user config (`PUT /api/config`, `DELETE
   /api/config/reset`), which requires an authenticated user and persists
   to that user's `UserConfig` DB row (`api/user_context.py`), NOT to any
   file. `test_user` below overrides auth so these can be exercised over
   HTTP without a real Clerk JWT.
"""

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import api.dependencies
from api.main import app
from api.auth import get_current_user
from api.database import SessionLocal
from api.models import User, UserConfig
from api.user_context import get_user_config
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def mock_config_path(tmp_path):
    """Fixture to provide a temporary JSON config path."""
    with patch("api.dependencies.CONFIG_PATH", tmp_path / "agent_config.json") as p_dep, \
         patch("api.routers.config.CONFIG_PATH", tmp_path / "agent_config.json") as p_router:
        yield p_dep


@pytest.fixture
def clean_config():
    """Ensure we start with a clean default config memory before each test."""
    api.dependencies._config.clear()
    api.dependencies._config.update(DEFAULT_CONFIG.copy())
    yield
    api.dependencies._config.clear()


@pytest.fixture
def test_user():
    """Create a throwaway User, override auth to act as them for
    /api/config's per-user endpoints, and clean up afterward (their User,
    UserConfig row, and the auth override) so this never pollutes the
    real dev DB or leaks into other tests.
    """
    db = SessionLocal()
    user = User(
        email="__test_config_persistence__@example.com",
        name="test",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield user
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.query(UserConfig).filter(UserConfig.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()


def test_init_graph_loads_persistent_json(mock_config_path, clean_config):
    """Test that init_graph loads and deep-merges an existing valid JSON."""
    test_json = {
        "execution": {"max_open_trades": 99},
        "new_key": "some_value"
    }
    with open(mock_config_path, "w") as f:
        json.dump(test_json, f)
        
    api.dependencies.init_graph()
    
    cfg = api.dependencies.get_config()
    assert cfg["execution"]["max_open_trades"] == 99
    assert cfg["new_key"] == "some_value"
    # Ensure default fields still exist (deep merge)
    assert "broker" in cfg["execution"]


def test_init_graph_fallback_if_no_file(mock_config_path, clean_config):
    """Test that init_graph falls back to DEFAULT_CONFIG if no file exists."""
    assert not mock_config_path.exists()
    
    api.dependencies.init_graph()
    
    cfg = api.dependencies.get_config()
    assert cfg["execution"]["broker"] == DEFAULT_CONFIG["execution"]["broker"]


def test_init_graph_fallback_if_corrupt_file(mock_config_path, clean_config):
    """Test that init_graph falls back to DEFAULT_CONFIG if JSON is invalid."""
    with open(mock_config_path, "w") as f:
        f.write("NOT JSON {")
        
    api.dependencies.init_graph()
    
    cfg = api.dependencies.get_config()
    assert cfg["execution"]["broker"] == DEFAULT_CONFIG["execution"]["broker"]


def test_update_config_writes_to_disk(test_user):
    """Test that PUT /api/config persists the merged config.

    Previously asserted this landed in agent_config.json — that was the
    single-tenant architecture's behavior. Per-user config now persists
    to that user's UserConfig DB row instead (api/user_context.py), which
    is what this now verifies.
    """
    client = TestClient(app)

    response = client.put("/api/config", json={"updates": {"portfolio": {"initial_cash": 50000}}})
    assert response.status_code == 200

    db = SessionLocal()
    try:
        saved = get_user_config(db, test_user.id)
    finally:
        db.close()
    assert saved["portfolio"]["initial_cash"] == 50000


def test_update_config_filters_secrets(test_user):
    """Test that sensitive keys are stored encrypted, not in the plain config JSON."""
    client = TestClient(app)

    updates = {
        "execution": {
            "api_key": "my_secret_key",
            "broker": "binance",
        }
    }

    response = client.put("/api/config", json={"updates": updates})
    assert response.status_code == 200

    db = SessionLocal()
    try:
        uc = db.query(UserConfig).filter(UserConfig.user_id == test_user.id).first()
        raw_json = json.loads(uc.config_json)
        encrypted_api_key = uc.encrypted_api_key
    finally:
        db.close()

    # api_key must not appear in the plain JSON blob...
    assert "api_key" not in raw_json.get("execution", {})
    # ...but must have actually been captured, just encrypted separately.
    assert encrypted_api_key
    # The non-secret field sent alongside it was still persisted as-is.
    # (Checked via the raw stored JSON, not get_user_config()'s merged
    # result — that helper deliberately forces broker back to "paper"
    # here since api_secret/exchange weren't also supplied; see
    # api/user_context.py's auto-upgrade safety net. Unrelated to what
    # this test checks.)
    assert raw_json["execution"]["broker"] == "binance"


def test_reset_config_endpoint(test_user):
    """Test that DELETE /api/config/reset clears the user's stored config back to defaults."""
    client = TestClient(app)
    client.put("/api/config", json={"updates": {"execution": {"broker": "hacked"}}})

    response = client.delete("/api/config/reset")
    assert response.status_code == 200

    db = SessionLocal()
    try:
        saved = get_user_config(db, test_user.id)
    finally:
        db.close()
    assert saved["execution"]["broker"] == DEFAULT_CONFIG["execution"]["broker"]
