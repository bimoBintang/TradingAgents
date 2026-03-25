"""Tests for entry price cache persistence to SQLite.

Covers:
- Database schema v2 migration
- CRUD operations (upsert, load, delete)
- CcxtBroker integration: load on init, write-through on fill, survive restart
"""

import os
import tempfile
import threading
from unittest.mock import MagicMock

import pytest

from tradingagents.storage.database import Database
from tradingagents.execution.order_models import OrderSide, OrderStatus
from tradingagents.execution.retry import RetryConfig


# ── Helper ────────────────────────────────────────────────────────────

def _make_tmp_db():
    """Create a Database with a temp file (auto-cleaned after test)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(db_path=path)
    return db, path


def _make_broker_with_db(db):
    """Create a CcxtBroker with mocked exchange + real DB."""
    from tradingagents.execution.brokers.ccxt_broker import CcxtBroker

    broker = object.__new__(CcxtBroker)
    broker.name = "ccxt_test"
    broker.exchange_id = "binance"
    broker.default_quote = "USDT"
    broker.exchange = MagicMock()
    broker._entry_price_cache = {}
    broker._cache_lock = threading.Lock()
    broker._retry_config = RetryConfig(max_retries=0)
    broker._db = db
    return broker


# ── Database Schema & CRUD Tests ──────────────────────────────────────

class TestDatabaseEntryPriceTable:

    def test_schema_v2_creates_table(self):
        db, path = _make_tmp_db()
        try:
            assert db.get_schema_version() == 2
            # Table should exist — inserting should not raise
            db.upsert_entry_price("BTC/USDT", 40000.0, 0.5)
        finally:
            db.close()
            os.unlink(path)

    def test_upsert_and_load(self):
        db, path = _make_tmp_db()
        try:
            db.upsert_entry_price("BTC/USDT", 40000.0, 0.5)
            db.upsert_entry_price("ETH/USDT", 3000.0, 2.0)

            result = db.load_entry_prices()

            assert len(result) == 2
            assert result["BTC/USDT"] == pytest.approx((40000.0, 0.5))
            assert result["ETH/USDT"] == pytest.approx((3000.0, 2.0))
        finally:
            db.close()
            os.unlink(path)

    def test_upsert_overwrites(self):
        db, path = _make_tmp_db()
        try:
            db.upsert_entry_price("BTC/USDT", 40000.0, 0.5)
            db.upsert_entry_price("BTC/USDT", 42000.0, 1.0)

            result = db.load_entry_prices()
            assert result["BTC/USDT"] == pytest.approx((42000.0, 1.0))
        finally:
            db.close()
            os.unlink(path)

    def test_delete_single(self):
        db, path = _make_tmp_db()
        try:
            db.upsert_entry_price("BTC/USDT", 40000.0, 0.5)
            db.upsert_entry_price("ETH/USDT", 3000.0, 2.0)

            db.delete_entry_price("BTC/USDT")

            result = db.load_entry_prices()
            assert "BTC/USDT" not in result
            assert "ETH/USDT" in result
        finally:
            db.close()
            os.unlink(path)

    def test_delete_all(self):
        db, path = _make_tmp_db()
        try:
            db.upsert_entry_price("BTC/USDT", 40000.0, 0.5)
            db.upsert_entry_price("ETH/USDT", 3000.0, 2.0)

            db.delete_entry_price()

            result = db.load_entry_prices()
            assert len(result) == 0
        finally:
            db.close()
            os.unlink(path)


# ── CcxtBroker + DB Integration Tests ────────────────────────────────

class TestBrokerDbIntegration:

    def test_broker_persists_on_fill(self):
        """place_order fill → entry price saved to DB."""
        db, path = _make_tmp_db()
        try:
            broker = _make_broker_with_db(db)

            broker.exchange.create_order.return_value = {
                "id": "ord_001",
                "filled": 0.5,
                "remaining": 0.0,
                "average": 42000.0,
                "status": "closed",
                "fee": {"cost": 0.5},
            }

            broker.place_order("BTC/USDT", OrderSide.BUY, 0.5)

            # Verify DB has the entry
            persisted = db.load_entry_prices()
            assert "BTC/USDT" in persisted
            assert persisted["BTC/USDT"] == pytest.approx((42000.0, 0.5))
        finally:
            db.close()
            os.unlink(path)

    def test_broker_survives_restart(self):
        """Simulate restart: cache loaded from DB on new broker init."""
        db, path = _make_tmp_db()
        try:
            # First broker: fill an order
            broker1 = _make_broker_with_db(db)
            broker1.exchange.create_order.return_value = {
                "id": "ord_002",
                "filled": 1.0,
                "remaining": 0.0,
                "average": 3500.0,
                "status": "closed",
                "fee": {"cost": 0.1},
            }
            broker1.place_order("ETH/USDT", OrderSide.BUY, 1.0)

            # Simulate restart: create new broker with same DB
            broker2 = _make_broker_with_db(db)
            # Manually load from DB (simulating __init__ behavior)
            persisted = db.load_entry_prices()
            broker2._entry_price_cache.update(persisted)

            assert "ETH/USDT" in broker2._entry_price_cache
            assert broker2._entry_price_cache["ETH/USDT"] == pytest.approx((3500.0, 1.0))
        finally:
            db.close()
            os.unlink(path)

    def test_clear_cache_also_clears_db(self):
        """clear_entry_cache should remove from both memory and DB."""
        db, path = _make_tmp_db()
        try:
            broker = _make_broker_with_db(db)
            db.upsert_entry_price("SOL/USDT", 150.0, 10.0)
            broker._entry_price_cache["SOL/USDT"] = (150.0, 10.0)

            broker.clear_entry_cache("SOL/USDT")

            assert "SOL/USDT" not in broker._entry_price_cache
            assert "SOL/USDT" not in db.load_entry_prices()
        finally:
            db.close()
            os.unlink(path)

    def test_sell_removes_from_db(self):
        """Selling full position removes entry from DB."""
        db, path = _make_tmp_db()
        try:
            broker = _make_broker_with_db(db)
            # Pre-populate
            broker._entry_price_cache["BTC/USDT"] = (40000.0, 1.0)
            db.upsert_entry_price("BTC/USDT", 40000.0, 1.0)

            broker.exchange.create_order.return_value = {
                "id": "ord_sell",
                "filled": 1.0,
                "remaining": 0.0,
                "average": 45000.0,
                "status": "closed",
                "fee": {"cost": 0.2},
            }
            broker.place_order("BTC/USDT", OrderSide.SELL, 1.0)

            assert "BTC/USDT" not in broker._entry_price_cache
            assert "BTC/USDT" not in db.load_entry_prices()
        finally:
            db.close()
            os.unlink(path)
