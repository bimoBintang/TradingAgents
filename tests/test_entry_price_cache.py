"""Tests for CcxtBroker entry price cache.

Verifies that get_positions() returns accurate entry prices (and thus
non-zero unrealized PnL) by using cached fill prices from place_order().
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.execution.order_models import OrderSide, OrderStatus


# ── Helper ────────────────────────────────────────────────────────────

def _make_broker():
    """Create a CcxtBroker with mocked exchange (bypass real connection)."""
    from tradingagents.execution.brokers.ccxt_broker import CcxtBroker

    broker = object.__new__(CcxtBroker)
    broker.name = "ccxt_test"
    broker.exchange_id = "binance"
    broker.default_quote = "USDT"
    broker.exchange = MagicMock()

    # Initialize the cache and lock manually (bypassing __init__)
    import threading
    from tradingagents.execution.retry import RetryConfig
    broker._entry_price_cache = {}
    broker._cache_lock = threading.Lock()
    broker._retry_config = RetryConfig(max_retries=0)  # No retries in tests
    broker._db = None
    return broker


# ── Cache Population Tests ────────────────────────────────────────────

class TestEntryCacheOnFill:
    """Cache should be populated when place_order() receives a fill."""

    def test_cache_populated_on_fill(self):
        broker = _make_broker()

        # Mock exchange returning a filled order
        broker.exchange.create_order.return_value = {
            "id": "ord_001",
            "filled": 0.5,
            "remaining": 0.0,
            "average": 42000.0,
            "price": 42000.0,
            "status": "closed",
            "fee": {"cost": 0.5},
        }

        result = broker.place_order("BTC/USDT", OrderSide.BUY, 0.5)

        assert result.status == OrderStatus.FILLED
        assert "BTC/USDT" in broker._entry_price_cache
        avg_price, qty = broker._entry_price_cache["BTC/USDT"]
        assert avg_price == pytest.approx(42000.0)
        assert qty == pytest.approx(0.5)

    def test_weighted_avg_on_partial_fills(self):
        broker = _make_broker()

        # First partial fill: 0.3 BTC at $40,000
        broker.exchange.create_order.return_value = {
            "id": "ord_002a",
            "filled": 0.3,
            "remaining": 0.7,
            "average": 40000.0,
            "status": "open",
            "fee": {"cost": 0.1},
        }
        broker.place_order("BTC/USDT", OrderSide.BUY, 1.0)

        # Second partial fill: 0.7 BTC at $44,000
        broker.exchange.create_order.return_value = {
            "id": "ord_002b",
            "filled": 0.7,
            "remaining": 0.0,
            "average": 44000.0,
            "status": "closed",
            "fee": {"cost": 0.2},
        }
        broker.place_order("BTC/USDT", OrderSide.BUY, 0.7)

        avg_price, total_qty = broker._entry_price_cache["BTC/USDT"]
        # weighted avg = (40000*0.3 + 44000*0.7) / 1.0 = 42800
        assert avg_price == pytest.approx(42800.0)
        assert total_qty == pytest.approx(1.0)

    def test_sell_reduces_cache_quantity(self):
        broker = _make_broker()

        # Pre-populate cache
        broker._entry_price_cache["ETH/USDT"] = (3000.0, 2.0)

        # Sell 1.5 ETH
        broker.exchange.create_order.return_value = {
            "id": "ord_sell",
            "filled": 1.5,
            "remaining": 0.0,
            "average": 3200.0,
            "status": "closed",
            "fee": {"cost": 0.1},
        }
        broker.place_order("ETH/USDT", OrderSide.SELL, 1.5)

        # Cache should still exist with reduced qty
        assert "ETH/USDT" in broker._entry_price_cache
        avg_price, qty = broker._entry_price_cache["ETH/USDT"]
        assert avg_price == pytest.approx(3000.0)  # entry price unchanged
        assert qty == pytest.approx(0.5)

    def test_sell_all_removes_cache(self):
        broker = _make_broker()

        broker._entry_price_cache["SOL/USDT"] = (150.0, 10.0)

        broker.exchange.create_order.return_value = {
            "id": "ord_sell_all",
            "filled": 10.0,
            "remaining": 0.0,
            "average": 160.0,
            "status": "closed",
            "fee": {"cost": 0.05},
        }
        broker.place_order("SOL/USDT", OrderSide.SELL, 10.0)

        assert "SOL/USDT" not in broker._entry_price_cache


# ── get_positions() Entry Price Resolution ────────────────────────────

class TestGetPositionsEntryPrice:
    """get_positions() should use cached entry price for accurate PnL."""

    def test_uses_cache_for_entry_price(self):
        broker = _make_broker()

        # Pre-populate cache: bought BTC at $40,000
        broker._entry_price_cache["BTC/USDT"] = (40000.0, 0.5)

        # Exchange reports balance + current price $45,000
        broker.exchange.fetch_balance.return_value = {
            "total": {"BTC": 0.5, "USDT": 1000.0},
        }
        broker.exchange.fetch_ticker.return_value = {
            "last": 45000.0,
            "info": {},
        }

        positions = broker.get_positions()

        assert len(positions) == 1
        pos = positions[0]
        assert pos.entry_price == pytest.approx(40000.0)
        assert pos.current_price == pytest.approx(45000.0)
        # PnL should be (45000 - 40000) * 0.5 = $2,500
        assert pos.unrealized_pnl == pytest.approx(2500.0)

    def test_fallback_to_exchange_entry_price(self):
        broker = _make_broker()

        # No cache — but exchange provides entryPrice
        broker.exchange.fetch_balance.return_value = {
            "total": {"ETH": 2.0, "USDT": 500.0},
        }
        broker.exchange.fetch_ticker.return_value = {
            "last": 3500.0,
            "info": {"entryPrice": "3000.0"},
        }

        positions = broker.get_positions()

        assert len(positions) == 1
        assert positions[0].entry_price == pytest.approx(3000.0)
        assert positions[0].unrealized_pnl == pytest.approx(1000.0)

    def test_fallback_to_current_price(self):
        broker = _make_broker()

        # No cache, no exchange entryPrice
        broker.exchange.fetch_balance.return_value = {
            "total": {"DOGE": 1000.0, "USDT": 100.0},
        }
        broker.exchange.fetch_ticker.return_value = {
            "last": 0.15,
            "info": {},
        }

        positions = broker.get_positions()

        assert len(positions) == 1
        # Falls back to current price → pnl ≈ 0
        assert positions[0].entry_price == pytest.approx(0.15)
        assert positions[0].unrealized_pnl == pytest.approx(0.0)


# ── clear_entry_cache() ──────────────────────────────────────────────

class TestClearEntryCache:

    def test_clear_single_symbol(self):
        broker = _make_broker()
        broker._entry_price_cache["BTC/USDT"] = (40000.0, 1.0)
        broker._entry_price_cache["ETH/USDT"] = (3000.0, 2.0)

        broker.clear_entry_cache("BTC/USDT")

        assert "BTC/USDT" not in broker._entry_price_cache
        assert "ETH/USDT" in broker._entry_price_cache

    def test_clear_all(self):
        broker = _make_broker()
        broker._entry_price_cache["BTC/USDT"] = (40000.0, 1.0)
        broker._entry_price_cache["ETH/USDT"] = (3000.0, 2.0)

        broker.clear_entry_cache()

        assert len(broker._entry_price_cache) == 0
