"""Tests for retry utility and its integration with CcxtBroker.

Covers the retry mechanism itself (exponential backoff, jitter, non-retryable
exceptions) and verifies that CcxtBroker methods correctly retry on
transient errors while place_order() does NOT retry.
"""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from tradingagents.execution.retry import RetryConfig, with_retry, _calculate_delay


# ── RetryConfig Tests ─────────────────────────────────────────────────

class TestRetryConfig:

    def test_from_config_dict(self):
        cfg = {
            "retry_max_attempts": 5,
            "retry_base_delay": 2.0,
            "retry_max_delay": 60.0,
            "retry_backoff_factor": 3.0,
        }
        rc = RetryConfig.from_config(cfg)
        assert rc.max_retries == 5
        assert rc.base_delay == 2.0
        assert rc.max_delay == 60.0
        assert rc.backoff_factor == 3.0

    def test_defaults_when_keys_missing(self):
        rc = RetryConfig.from_config({})
        assert rc.max_retries == 3
        assert rc.base_delay == 1.0


# ── Core Retry Logic Tests ───────────────────────────────────────────

class TestWithRetry:

    def test_succeeds_first_try(self):
        """No retries needed when function succeeds immediately."""
        func = MagicMock(return_value="ok")
        result = with_retry(func, config=RetryConfig(max_retries=3))

        assert result == "ok"
        assert func.call_count == 1

    def test_succeeds_after_retries(self):
        """Retries transient errors and eventually succeeds."""
        import ccxt

        func = MagicMock(
            side_effect=[ccxt.NetworkError("fail"), ccxt.NetworkError("fail"), "ok"]
        )
        config = RetryConfig(max_retries=3, base_delay=0.01, max_delay=0.05)

        result = with_retry(func, config=config, operation_name="test_op")

        assert result == "ok"
        assert func.call_count == 3

    def test_exhausts_retries_raises(self):
        """Raises the last error when all retries are exhausted."""
        import ccxt

        func = MagicMock(side_effect=ccxt.NetworkError("still failing"))
        config = RetryConfig(max_retries=2, base_delay=0.01, max_delay=0.05)

        with pytest.raises(ccxt.NetworkError, match="still failing"):
            with_retry(func, config=config)

        assert func.call_count == 3  # 1 initial + 2 retries

    def test_non_retryable_exception_immediate(self):
        """Non-retryable exceptions are raised immediately without retry."""
        import ccxt

        func = MagicMock(side_effect=ccxt.InsufficientFunds("no money"))
        config = RetryConfig(max_retries=3, base_delay=0.01)

        with pytest.raises(ccxt.InsufficientFunds, match="no money"):
            with_retry(func, config=config)

        # Should NOT have retried — only 1 call
        assert func.call_count == 1

    def test_zero_retries_no_retry(self):
        """With max_retries=0, function is called once and failure raises."""
        import ccxt

        func = MagicMock(side_effect=ccxt.NetworkError("down"))
        config = RetryConfig(max_retries=0)

        with pytest.raises(ccxt.NetworkError):
            with_retry(func, config=config)

        assert func.call_count == 1


class TestCalculateDelay:

    def test_exponential_growth(self):
        config = RetryConfig(base_delay=1.0, backoff_factor=2.0, max_delay=100.0, jitter_range=0.0)
        # Attempt 0: 1.0, Attempt 1: 2.0, Attempt 2: 4.0
        assert _calculate_delay(0, config) == pytest.approx(1.0)
        assert _calculate_delay(1, config) == pytest.approx(2.0)
        assert _calculate_delay(2, config) == pytest.approx(4.0)

    def test_max_delay_cap(self):
        config = RetryConfig(base_delay=1.0, backoff_factor=10.0, max_delay=5.0, jitter_range=0.0)
        # 1 * 10^3 = 1000, but capped at 5.0
        assert _calculate_delay(3, config) == pytest.approx(5.0)

    def test_jitter_applies(self):
        config = RetryConfig(base_delay=10.0, backoff_factor=1.0, jitter_range=0.2)
        delays = [_calculate_delay(0, config) for _ in range(100)]
        # All should be within 10 * (0.8 to 1.2) = 8.0 to 12.0
        assert all(8.0 <= d <= 12.0 for d in delays)


# ── CcxtBroker Integration Tests ─────────────────────────────────────

def _make_broker_with_retry():
    """Create a CcxtBroker with retry and mocked exchange."""
    from tradingagents.execution.brokers.ccxt_broker import CcxtBroker
    import threading

    broker = object.__new__(CcxtBroker)
    broker.name = "ccxt_test"
    broker.exchange_id = "binance"
    broker.default_quote = "USDT"
    broker.exchange = MagicMock()
    broker._entry_price_cache = {}
    broker._cache_lock = threading.Lock()
    broker._retry_config = RetryConfig(max_retries=2, base_delay=0.01, max_delay=0.05)
    broker._db = None
    # place_order() branches on self.market_type — object.__new__() skips
    # __init__, so this must be set explicitly (see test_entry_price_cache.py).
    broker.market_type = "spot"
    return broker


class TestCcxtBrokerRetryIntegration:

    def test_get_balance_retries_on_network_error(self):
        import ccxt

        broker = _make_broker_with_retry()
        broker.exchange.fetch_balance.side_effect = [
            ccxt.NetworkError("timeout"),
            {"free": {"USDT": 1000.0}, "total": {"USDT": 1000.0}},
        ]

        result = broker.get_balance()

        assert result["cash"] == 1000.0
        assert broker.exchange.fetch_balance.call_count == 2

    def test_get_current_price_retries(self):
        import ccxt

        broker = _make_broker_with_retry()
        broker.exchange.fetch_ticker.side_effect = [
            ccxt.RequestTimeout("slow"),
            {"last": 42000.0},
        ]

        result = broker.get_current_price("BTC/USDT")

        assert result == 42000.0
        assert broker.exchange.fetch_ticker.call_count == 2

    def test_place_order_does_NOT_retry(self):
        """place_order should NOT retry to prevent double-orders."""
        import ccxt
        from tradingagents.execution.order_models import OrderSide

        broker = _make_broker_with_retry()
        broker.exchange.create_order.side_effect = ccxt.NetworkError("timeout")

        # place_order catches and returns REJECTED, does NOT retry
        result = broker.place_order("BTC/USDT", OrderSide.BUY, 1.0)

        # create_order should only be called ONCE
        assert broker.exchange.create_order.call_count == 1
