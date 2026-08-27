"""Tests for the chart-control service (Fase 7) — api/chart_control.py.

Covers: the ephemeral state cache, and that every driving action
degrades gracefully (delivered=False with a reason) when the user's
dashboard has no open WS connection, rather than silently no-op'ing or
raising into a caller (an MCP tool, or the REST router) that has no way
to know whether anything actually happened.
"""

from unittest.mock import AsyncMock, patch

import pytest

from api import chart_control


@pytest.fixture(autouse=True)
def _clean_state():
    """Each test starts with a clean in-memory state cache — it's a
    module-level dict, so tests would otherwise leak into each other."""
    chart_control._last_known_state.clear()
    yield
    chart_control._last_known_state.clear()


# ── State cache ──────────────────────────────────────────────────────

def test_record_and_get_chart_state_round_trip():
    assert chart_control.get_chart_state(1) is None

    chart_control.record_chart_state(1, {"ticker": "AAPL", "timeframe": "1D", "activeIndicator": "all"})

    assert chart_control.get_chart_state(1) == {"ticker": "AAPL", "timeframe": "1D", "activeIndicator": "all"}
    assert chart_control.get_chart_state(2) is None  # scoped per user


# ── Not-connected degradation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_chart_view_not_connected():
    with patch("api.chart_control.manager.is_connected", return_value=False):
        result = await chart_control.set_chart_view(1, "AAPL")
    assert result == {"delivered": False, "reason": chart_control._NOT_CONNECTED}


@pytest.mark.asyncio
async def test_annotate_chart_patterns_not_connected():
    with patch("api.chart_control.manager.is_connected", return_value=False):
        result = await chart_control.annotate_chart_patterns(1, "AAPL")
    assert result["delivered"] is False


@pytest.mark.asyncio
async def test_highlight_price_level_not_connected():
    with patch("api.chart_control.manager.is_connected", return_value=False):
        result = await chart_control.highlight_price_level(1, "AAPL", 150.0, "Support")
    assert result["delivered"] is False


@pytest.mark.asyncio
async def test_clear_ai_highlights_not_connected():
    with patch("api.chart_control.manager.is_connected", return_value=False):
        result = await chart_control.clear_ai_highlights(1, "AAPL")
    assert result["delivered"] is False


# ── Connected: verify the exact WS payload sent ─────────────────────

@pytest.mark.asyncio
async def test_set_chart_view_sends_correct_payload():
    with patch("api.chart_control.manager.is_connected", return_value=True), \
         patch("api.chart_control.manager.send_json", new_callable=AsyncMock) as mock_send:
        result = await chart_control.set_chart_view(1, "aapl", "1H", "sma")

    assert result == {"delivered": True}
    mock_send.assert_awaited_once_with(1, {
        "type": "chart_command",
        "action": "set_view",
        "ticker": "AAPL",  # uppercased
        "timeframe": "1H",
        "indicator": "sma",
    })


@pytest.mark.asyncio
async def test_highlight_price_level_sends_correct_payload():
    with patch("api.chart_control.manager.is_connected", return_value=True), \
         patch("api.chart_control.manager.send_json", new_callable=AsyncMock) as mock_send:
        result = await chart_control.highlight_price_level(1, "aapl", 150.5, "Resistance")

    assert result == {"delivered": True}
    mock_send.assert_awaited_once_with(1, {
        "type": "chart_command",
        "action": "highlight_price_level",
        "ticker": "AAPL",
        "price": 150.5,
        "label": "Resistance",
        "color": "#f59e0b",  # default
    })


@pytest.mark.asyncio
async def test_annotate_chart_patterns_sends_correct_payload():
    with patch("api.chart_control.manager.is_connected", return_value=True), \
         patch("api.chart_control.manager.send_json", new_callable=AsyncMock) as mock_send:
        await chart_control.annotate_chart_patterns(1, "aapl", "1h")

    mock_send.assert_awaited_once_with(1, {
        "type": "chart_command",
        "action": "annotate_patterns",
        "ticker": "AAPL",
        "timeframe": "1h",
    })
