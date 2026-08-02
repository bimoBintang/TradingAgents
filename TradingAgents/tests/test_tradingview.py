"""
Unit tests for TradingView dataflow module, caching, parameter validation, and interface integration.
"""

import time
import pytest
from tradingagents.dataflows.tradingview import (
    fetch_tradingview_ta,
    validate_tradingview_params,
    clear_tradingview_cache,
    TradingViewFetchError,
    _CACHE,
)
from tradingagents.dataflows.interface import route_to_vendor, VENDOR_METHODS


def setup_function():
    """Clear cache before each test."""
    clear_tradingview_cache()


def test_validate_tradingview_params_valid():
    sym, scr, exch, tv_int = validate_tradingview_params("btcusdt", "CRYPTO", "binance", "1h")
    assert sym == "BTCUSDT"
    assert scr == "crypto"
    assert exch == "BINANCE"


def test_validate_tradingview_params_invalid_interval():
    with pytest.raises(ValueError, match="Invalid interval"):
        validate_tradingview_params("BTCUSDT", interval="invalid_timeframe")


def test_fetch_tradingview_ta_live():
    """Test fetching live TA data from TradingView for BTCUSDT."""
    data = fetch_tradingview_ta(symbol="BTCUSDT", exchange="BINANCE", screener="crypto", interval="1h")
    assert isinstance(data, dict)
    assert data["symbol"] == "BTCUSDT"
    assert data["recommendation"] in ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]
    assert "RSI" in data["indicators"]
    assert "summary" in data


def test_tradingview_caching():
    """Verify that identical request hits cache on second call."""
    clear_tradingview_cache()

    # First call - cache miss
    t0 = time.time()
    res1 = fetch_tradingview_ta(symbol="BTCUSDT", exchange="BINANCE", interval="1h", use_cache=True)
    t1 = time.time()
    dur1 = t1 - t0

    # Second call - cache hit (should be near instant < 5ms)
    t2 = time.time()
    res2 = fetch_tradingview_ta(symbol="BTCUSDT", exchange="BINANCE", interval="1h", use_cache=True)
    t3 = time.time()
    dur2 = t3 - t2

    assert res1["recommendation"] == res2["recommendation"]
    assert dur2 < dur1
    assert len(_CACHE) == 1


def test_interface_routing_tradingview():
    """Verify routing via dataflows interface."""
    assert "tradingview" in VENDOR_METHODS["get_indicators"]
    data = route_to_vendor("get_indicators", vendor="tradingview", symbol="BTCUSDT", screener="crypto", exchange="BINANCE", interval="1h")
    assert "recommendation" in data
    assert "indicators" in data


def test_cache_ttl_expiration_exact():
    """Test Cache HIT -> Expiration after 60s -> Cache MISS transition."""
    from unittest.mock import patch
    clear_tradingview_cache()

    start_time = 1000.0

    # 1. First fetch at t=1000s -> Cache MISS
    with patch("time.time", return_value=start_time):
        fetch_tradingview_ta(symbol="BTCUSDT", exchange="BINANCE", interval="1h", use_cache=True)
        assert len(_CACHE) == 1

    # 2. Fetch at t=1030s (within 60s TTL) -> Cache HIT
    with patch("time.time", return_value=start_time + 30.0):
        data_hit = fetch_tradingview_ta(symbol="BTCUSDT", exchange="BINANCE", interval="1h", use_cache=True)
        assert data_hit["symbol"] == "BTCUSDT"
        assert len(_CACHE) == 1

    # 3. Fetch at t=1061s (after 60s TTL) -> Cache EXPIRED & MISS
    with patch("time.time", return_value=start_time + 61.0):
        from tradingagents.dataflows.tradingview import _get_from_cache
        cache_key = ("BTCUSDT", "crypto", "BINANCE", "1h")
        expired_val = _get_from_cache(cache_key)
        assert expired_val is None  # Verified cache expired cleanly
