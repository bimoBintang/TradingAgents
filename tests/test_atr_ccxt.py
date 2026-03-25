"""Tests for _get_atr_ccxt() and the modified _get_atr() delegation logic.

All broker/exchange interactions are mocked — no real network calls.
"""

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.brokers.broker_base import BaseBroker


# ── Helpers ───────────────────────────────────────────────────────────

def _make_engine(broker: BaseBroker | None = None) -> ExecutionEngine:
    """Create a minimal ExecutionEngine with a mocked broker."""
    if broker is None:
        broker = MagicMock(spec=BaseBroker)
    pm = MagicMock(spec=PortfolioManager)
    pm.positions = {}
    pm.max_drawdown_pct = 0.0
    return ExecutionEngine(
        broker=broker,
        portfolio_manager=pm,
        atr_timeframe="1h",
    )


def _make_ohlcv(n: int = 15) -> list[list[float]]:
    """Generate deterministic OHLCV bars for testing.

    Each bar: [timestamp, open, high, low, close, volume]
    Uses a simple pattern so True Range can be manually verified.

    Bar layout (i starts at 0):
        open  = 100 + i
        high  = 105 + i
        low   =  95 + i
        close = 102 + i

    True Range for bar i (i >= 1):
        H - L              = (105+i) - (95+i)        = 10
        |H - prev_close|   = |(105+i) - (102+(i-1))| = |4|  = 4
        |L - prev_close|   = |(95+i)  - (102+(i-1))| = |-6| = 6
        TR = max(10, 4, 6) = 10
    """
    return [
        [1700000000 + i * 3600, 100 + i, 105 + i, 95 + i, 102 + i, 1000]
        for i in range(n)
    ]


# ── Test Cases ────────────────────────────────────────────────────────

class TestGetAtrCcxt:
    """Tests for the new _get_atr_ccxt() method."""

    def test_basic_atr_calculation(self):
        """Mock fetch_ohlcv with known data and verify ATR value."""
        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.return_value = _make_ohlcv(15)

        engine = _make_engine(broker)
        result = engine._get_atr_ccxt("BTC/USDT", period=14)

        # All TRs = 10, so ATR = 10.0
        assert result is not None
        assert result == pytest.approx(10.0)
        broker.exchange.fetch_ohlcv.assert_called_once_with(
            "BTC/USDT", timeframe="1h", limit=15,
        )

    def test_insufficient_data_returns_none(self):
        """Return None when exchange provides fewer bars than needed."""
        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.return_value = _make_ohlcv(5)  # need 15

        engine = _make_engine(broker)
        result = engine._get_atr_ccxt("ETH/USDT", period=14)

        assert result is None

    def test_network_error_returns_none(self):
        """Return None on ccxt.NetworkError without crashing."""
        import ccxt

        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.side_effect = ccxt.NetworkError("timeout")

        engine = _make_engine(broker)
        result = engine._get_atr_ccxt("BTC/USDT")

        assert result is None

    def test_exchange_error_returns_none(self):
        """Return None on ccxt.ExchangeError without crashing."""
        import ccxt

        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.side_effect = ccxt.ExchangeError("bad symbol")

        engine = _make_engine(broker)
        result = engine._get_atr_ccxt("INVALID/PAIR")

        assert result is None

    def test_non_ccxt_broker_returns_none(self):
        """Return None when broker has no 'exchange' attribute (e.g. PaperBroker)."""
        broker = MagicMock(spec=BaseBroker)
        # BaseBroker spec does NOT have .exchange, so getattr returns None
        if hasattr(broker, "exchange"):
            del broker.exchange

        engine = _make_engine(broker)
        result = engine._get_atr_ccxt("BTC/USDT")

        assert result is None


class TestGetAtrDelegation:
    """Tests for the modified _get_atr() that delegates to _get_atr_ccxt()."""

    def test_ccxt_ticker_delegates(self):
        """_get_atr('BTC/USDT') should call _get_atr_ccxt()."""
        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.return_value = _make_ohlcv(15)

        engine = _make_engine(broker)

        with patch.object(engine, "_get_atr_ccxt", wraps=engine._get_atr_ccxt) as mock:
            engine._get_atr("BTC/USDT")
            mock.assert_called_once_with("BTC/USDT", 14)

    def test_stock_ticker_uses_yfinance_path(self):
        """_get_atr('NVDA') should NOT call _get_atr_ccxt()."""
        engine = _make_engine()

        with patch.object(engine, "_get_atr_ccxt") as mock_ccxt:
            # yfinance path will likely fail in test, but we only check delegation
            engine._get_atr("NVDA")
            mock_ccxt.assert_not_called()

    def test_cache_prevents_redundant_calls(self):
        """Calling _get_atr twice for same ticker reuses cached value."""
        broker = MagicMock(spec=BaseBroker)
        broker.exchange = MagicMock()
        broker.exchange.fetch_ohlcv.return_value = _make_ohlcv(15)

        engine = _make_engine(broker)

        result1 = engine._get_atr("BTC/USDT")
        result2 = engine._get_atr("BTC/USDT")

        assert result1 == result2
        # fetch_ohlcv should only be called once (second call hits cache)
        assert broker.exchange.fetch_ohlcv.call_count == 1
