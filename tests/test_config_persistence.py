"""Unit tests for the agent runtime config persistence."""

import os
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

import api.dependencies
from api.main import app
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


def test_update_config_writes_to_disk(mock_config_path, clean_config):
    """Test that PUT /api/config writes the merged config to disk atomically."""
    client = TestClient(app)
    
    response = client.put("/api/config", json={"updates": {"portfolio": {"initial_cash": 50000}}})
    assert response.status_code == 200
    
    assert mock_config_path.exists()
    with open(mock_config_path, "r") as f:
        saved = json.load(f)
        
    assert saved["portfolio"]["initial_cash"] == 50000


def test_update_config_filters_secrets(mock_config_path, clean_config):
    """Test that sensitive keys are not written to the JSON file."""
    client = TestClient(app)
    
    updates = {
        "execution": {
            "api_key": "my_secret_key",
            "broker": "binance"
        }
    }
    
    response = client.put("/api/config", json={"updates": updates})
    assert response.status_code == 200
    
    with open(mock_config_path, "r") as f:
        saved = json.load(f)
        
    assert "broker" in saved["execution"]
    assert "api_key" not in saved["execution"]


def test_reset_config_endpoint(mock_config_path, clean_config):
    """Test that DELETE /api/config/reset clears file and memory."""
    with open(mock_config_path, "w") as f:
        json.dump({"execution": {"broker": "hacked"}}, f)
        
    api.dependencies._config["execution"]["broker"] = "hacked"
    
    client = TestClient(app)
    response = client.delete("/api/config/reset")
    
    assert response.status_code == 200
    assert not mock_config_path.exists()
    assert api.dependencies._config["execution"]["broker"] == DEFAULT_CONFIG["execution"]["broker"]
