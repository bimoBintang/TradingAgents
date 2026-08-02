"""
FastAPI unit tests for TradingView API router (/api/tradingview/*).
"""

import sys
import os
import pytest
from fastapi.testclient import TestClient

# Ensure sys.path includes TradingAgents directory
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from api.main import app
from api.routers.tradingview import validate_pinescript_syntax
from fastapi import HTTPException


@pytest.fixture
def client():
    return TestClient(app)


def test_get_mcp_status(client):
    """Test GET /api/tradingview/mcp-status returns CDP status information."""
    response = client.get("/api/tradingview/mcp-status")
    assert response.status_code == 200
    data = response.json()
    assert data["cdp_host"] == "127.0.0.1"
    assert data["cdp_port"] == 9222
    assert "is_connected" in data
    assert "mode" in data
    assert "fallback_active" in data


def test_get_tradingview_analysis_endpoint(client):
    """Test GET /api/tradingview/analysis returns quantitative TA + ChartVision report."""
    response = client.get("/api/tradingview/analysis?ticker=BTCUSDT&timeframe=1h")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["ticker"] == "BTCUSDT"
    assert "quantitative_ta" in data
    assert "chart_vision_report" in data
    assert "recommendation" in data["quantitative_ta"]


def test_pinescript_auth_guard(client):
    """Test POST /api/tradingview/pinescript without auth header returns 401 Unauthorized."""
    response = client.post("/api/tradingview/pinescript", json={
        "code": "//@version=5\nstrategy('Test', overlay=true)",
        "script_name": "Test_Strategy"
    })
    # Since auth is required, should return 401 Unauthorized
    assert response.status_code in [401, 403]


def test_pinescript_syntax_validation():
    """Test validate_pinescript_syntax dry-run validator."""
    # 1. Valid syntax
    validate_pinescript_syntax("//@version=5\nindicator('My Indicator', overlay=true)\nplot(close)")

    # 2. Empty code -> raises 400
    with pytest.raises(HTTPException) as exc1:
        validate_pinescript_syntax("")
    assert exc1.value.status_code == 400

    # 3. Missing definition header -> raises 400
    with pytest.raises(HTTPException) as exc2:
        validate_pinescript_syntax("//@version=5\nx = 10 + 20")
    assert exc2.value.status_code == 400

    # 4. Unbalanced parentheses -> raises 400
    with pytest.raises(HTTPException) as exc3:
        validate_pinescript_syntax("//@version=5\nindicator('Test' overlay=true\nplot(close)")
    assert exc3.value.status_code == 400
