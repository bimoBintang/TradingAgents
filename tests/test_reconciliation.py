"""Tests for ExecutionEngine.reconcile() — startup position sync.

Covers:
- No drift (identical state)
- Exchange has extra position (synced to portfolio)
- Local has stale position (removed from portfolio)
- Matching positions price update
- Broker error handled gracefully
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.order_models import OrderSide, PositionInfo
from tradingagents.execution.portfolio_manager import PortfolioManager


# ── Helper ────────────────────────────────────────────────────────────

def _make_engine():
    """Create a minimal ExecutionEngine for reconciliation tests."""
    broker = PaperBroker(initial_cash=10_000.0, commission_pct=0.0, slippage_pct=0.0)
    portfolio = PortfolioManager(initial_cash=10_000.0, max_total_positions=10)
    engine = ExecutionEngine(
        broker=broker,
        portfolio_manager=portfolio,
        cooldown_seconds=0,
        require_confirmation=False,
    )
    return engine, broker, portfolio


def _inject_broker_position(broker, ticker, qty=1.0, entry=100.0, side=OrderSide.BUY):
    """Inject a position directly into PaperBroker's internal state."""
    broker._positions[ticker] = {
        "side": side,
        "quantity": qty,
        "entry_price": entry,
        "entry_time": datetime.utcnow(),
    }


# ── Test Cases ────────────────────────────────────────────────────────

class TestReconciliation:

    def test_no_drift(self):
        """Identical state on exchange and local -> nothing to do."""
        engine, broker, portfolio = _make_engine()

        broker.set_price("NVDA", 120.0)
        _inject_broker_position(broker, "NVDA", qty=1.0, entry=100.0)
        portfolio.open_position("NVDA", OrderSide.BUY, 1.0, 100.0)

        report = engine.reconcile()

        assert len(report["added"]) == 0
        assert len(report["removed"]) == 0
        assert len(report["updated"]) == 1
        assert "NVDA" in report["updated"]
        assert len(report["errors"]) == 0

    def test_exchange_has_extra_position(self):
        """Exchange has position missing from local -> added."""
        engine, broker, portfolio = _make_engine()

        broker.set_price("AAPL", 150.0)
        _inject_broker_position(broker, "AAPL", qty=2.0, entry=140.0)

        report = engine.reconcile()

        assert "AAPL" in report["added"]
        assert "AAPL" in portfolio.positions

    def test_local_has_stale_position(self):
        """Local has position no longer on exchange -> removed."""
        engine, broker, portfolio = _make_engine()

        portfolio.open_position("MSFT", OrderSide.BUY, 1.0, 300.0)

        report = engine.reconcile()

        assert "MSFT" in report["removed"]
        assert "MSFT" not in portfolio.positions

    def test_price_update(self):
        """Matching positions get current_price updated."""
        engine, broker, portfolio = _make_engine()

        broker.set_price("NVDA", 130.0)
        _inject_broker_position(broker, "NVDA", qty=1.0, entry=100.0)
        portfolio.open_position("NVDA", OrderSide.BUY, 1.0, 100.0)

        report = engine.reconcile()

        assert portfolio.positions["NVDA"].current_price == pytest.approx(130.0, rel=0.01)
        assert "NVDA" in report["updated"]

    def test_broker_error_graceful(self):
        """Broker raises exception -> reconciliation aborted gracefully."""
        engine, broker, portfolio = _make_engine()

        broker.get_positions = MagicMock(side_effect=ConnectionError("network down"))

        report = engine.reconcile()

        assert len(report["errors"]) >= 1
        assert "broker.get_positions() failed" in report["errors"][0]
        assert "aborted" in report["summary"].lower()
