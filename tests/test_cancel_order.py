"""Tests for the fixed cancel_order() with optional symbol parameter.

Covers CCXT cancel with/without symbol, error handling for
ArgumentsRequired and ExchangeError, and backward compatibility
for PaperBroker.
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.order_models import OrderStatus


# ── Helpers ───────────────────────────────────────────────────────────

def _make_ccxt_broker():
    """Create a CcxtBroker with a mocked exchange (bypass real connection)."""
    from tradingagents.execution.brokers.ccxt_broker import CcxtBroker

    broker = object.__new__(CcxtBroker)
    broker.name = "ccxt_test"
    broker.exchange_id = "binance"
    broker.default_quote = "USDT"
    broker.exchange = MagicMock()
    return broker


# ── CcxtBroker Tests ─────────────────────────────────────────────────

class TestCcxtCancelOrder:
    """Tests for CcxtBroker.cancel_order()."""

    def test_cancel_with_symbol(self):
        """When symbol is provided, it should be passed to exchange."""
        broker = _make_ccxt_broker()
        broker.exchange.cancel_order.return_value = {"status": "canceled"}

        result = broker.cancel_order("order123", symbol="BTC/USDT")

        assert result is True
        broker.exchange.cancel_order.assert_called_once_with("order123", "BTC/USDT")

    def test_cancel_without_symbol(self):
        """When symbol is None, cancel_order should be called with ID only."""
        broker = _make_ccxt_broker()
        broker.exchange.cancel_order.return_value = {"status": "canceled"}

        result = broker.cancel_order("order456")

        assert result is True
        broker.exchange.cancel_order.assert_called_once_with("order456")

    def test_cancel_arguments_required_error(self):
        """Should return False and print warning on ArgumentsRequired."""
        import ccxt

        broker = _make_ccxt_broker()
        broker.exchange.cancel_order.side_effect = ccxt.ArgumentsRequired(
            "cancel_order requires symbol argument"
        )

        result = broker.cancel_order("order789")

        assert result is False

    def test_cancel_exchange_error(self):
        """Should return False on ExchangeError."""
        import ccxt

        broker = _make_ccxt_broker()
        broker.exchange.cancel_order.side_effect = ccxt.ExchangeError(
            "Order not found"
        )

        result = broker.cancel_order("order_bad", symbol="ETH/USDT")

        assert result is False

    def test_cancel_generic_exception(self):
        """Should return False on any unexpected exception."""
        broker = _make_ccxt_broker()
        broker.exchange.cancel_order.side_effect = RuntimeError("network down")

        result = broker.cancel_order("order_fail")

        assert result is False


# ── PaperBroker Backward Compatibility ───────────────────────────────

class TestPaperBrokerCancelCompat:
    """PaperBroker.cancel_order() must accept both old and new signatures."""

    def test_cancel_without_symbol(self):
        """Old calling convention: cancel_order(order_id) still works."""
        broker = PaperBroker(initial_cash=1000.0)
        # No pending order → returns False, but shouldn't crash
        result = broker.cancel_order("nonexistent_order")
        assert result is False

    def test_cancel_with_symbol_ignored(self):
        """New calling convention: cancel_order(order_id, symbol) accepted."""
        broker = PaperBroker(initial_cash=1000.0)
        result = broker.cancel_order("nonexistent_order", symbol="AAPL")
        assert result is False
