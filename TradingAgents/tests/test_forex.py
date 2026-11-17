"""Forex support: symbol mapping, market hours, data routing, analyst set, market context."""
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from tradingagents.dataflows.symbols import asset_class, yf_symbol, forex_market_open


@pytest.mark.parametrize("t,cls", [
    ("EURUSD", "forex"), ("EUR/USD", "forex"), ("eurusd=x", "forex"), ("GBPJPY", "forex"),
    ("XAUUSD", "forex"), ("BTCUSD", "crypto"), ("BTC-USD", "crypto"), ("ETH/USDT", "crypto"),
    ("NVDA", "stock"), ("AAPL", "stock"),
])
def test_asset_class(t, cls):
    assert asset_class(t) == cls


def test_yf_symbol_only_rewrites_forex():
    assert yf_symbol("EURUSD") == "EURUSD=X"
    assert yf_symbol("EUR/USD") == "EURUSD=X"
    assert yf_symbol("EURUSD=X") == "EURUSD=X"
    assert yf_symbol("XAUUSD") == "GC=F"
    for v in ("NVDA", "BTC-USD", "2026-01-31", "AAPL,MSFT", 5, None):
        assert yf_symbol(v) == v


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


@pytest.mark.parametrize("when,expected", [
    (_utc(2026, 11, 14, 12), False),       # Saturday
    (_utc(2026, 11, 13, 21, 59), True),    # Friday just before close
    (_utc(2026, 11, 13, 22, 0), False),    # Friday close
    (_utc(2026, 11, 15, 21, 59), False),   # Sunday before open
    (_utc(2026, 11, 15, 22, 0), True),     # Sunday open
    (_utc(2026, 11, 16, 3, 0), True),      # Monday
])
def test_forex_market_open(when, expected):
    assert forex_market_open(when) is expected


def test_route_to_vendor_maps_symbol_for_yfinance_only(monkeypatch):
    from tradingagents.dataflows import interface as I
    seen = []

    def fake(symbol, start_date=None):
        seen.append(symbol)
        return "ok"
    monkeypatch.setitem(I.VENDOR_METHODS, "get_stock_data", {"yfinance": fake})
    monkeypatch.setattr(I, "get_vendor", lambda *a, **k: "yfinance")
    I.route_to_vendor("get_stock_data", "EURUSD", "2026-01-01")
    I.route_to_vendor("get_stock_data", "NVDA", "2026-01-01")
    I.route_to_vendor("get_stock_data", symbol="GBPUSD")
    assert seen == ["EURUSD=X", "NVDA", "GBPUSD=X"]


def _sched(monkeypatch, now):
    pytest.importorskip("apscheduler")
    from tradingagents.scheduler import scheduler as S
    from tradingagents.dataflows import symbols
    s = S.TradingScheduler.__new__(S.TradingScheduler)
    s.market_hours_only, s.crypto_24_7 = True, True
    s.market_open_hour, s.market_close_hour = 9, 16
    monkeypatch.setattr(symbols, "forex_market_open", lambda n=None: forex_market_open(now))
    return s


def test_scheduler_forex_follows_forex_hours_not_crypto(monkeypatch):
    sat = _sched(monkeypatch, _utc(2026, 11, 14, 12))
    assert sat._is_market_open("EURUSD") is False      # used to count as crypto (24/7)
    assert sat._is_market_open("BTC-USD") is True
    mon = _sched(monkeypatch, _utc(2026, 11, 16, 12))
    assert mon._is_market_open("EURUSD") is True


def test_default_analysts_follow_broker():
    from tradingagents.graph.trading_graph import ALL_ANALYSTS, FOREX_ANALYSTS
    assert "fundamentals" in ALL_ANALYSTS and "onchain" in ALL_ANALYSTS
    assert not {"fundamentals", "onchain", "social"} & set(FOREX_ANALYSTS)
    assert {"ict", "chart_vision", "market"} <= set(FOREX_ANALYSTS)


def test_market_context_for_mt5_is_forex_not_usdt():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    ctx = TradingAgentsGraph._build_market_context(NS(config={"execution": {"broker": "mt5", "max_leverage": 7}}))
    assert "FOREX" in ctx and "7x" in ctx and "USDT" not in ctx
    spot = TradingAgentsGraph._build_market_context(NS(config={"execution": {"broker": "paper"}}))
    assert "SPOT MODE" in spot


def test_ict_forex_uses_yfinance_candles(monkeypatch):
    pytest.importorskip("orchestrator")
    import pandas as pd
    from orchestrator.sdk import ict_agent as A
    idx = pd.date_range("2026-01-01", periods=40, freq="h")
    df = pd.DataFrame({"Open": 1.0, "High": 1.1, "Low": 0.9, "Close": 1.05}, index=idx)
    import yfinance
    seen = {}

    class T:
        def __init__(self, s): seen["s"] = s
        def history(self, **k): return df
    monkeypatch.setattr(yfinance, "Ticker", T)
    out = A._fetch_ohlc("EURUSD", "1h")
    assert seen["s"] == "EURUSD=X" and len(out["closes"]) == 40


def test_cli_config_deep_merges(tmp_path):
    import json
    from tradingagents.cli import _load_config
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"execution": {"broker": "mt5"}, "scheduler": {"watchlist": ["EURUSD"]}}))
    cfg = _load_config(str(p))
    assert cfg["execution"]["broker"] == "mt5"
    assert "max_daily_loss_pct" in cfg["execution"] or len(cfg["execution"]) > 3  # defaults kept
    assert cfg["scheduler"]["watchlist"] == ["EURUSD"]


def test_yfinance_vendor_keeps_forex_precision(monkeypatch):
    import pandas as pd
    from tradingagents.dataflows import y_finance as Y
    idx = pd.date_range("2026-11-02", periods=3, freq="D")
    df = pd.DataFrame({"Open": 1.12345, "High": 1.12399, "Low": 1.12301, "Close": 1.12367}, index=idx)

    class T:
        def __init__(self, s): pass
        def history(self, **k): return df.copy()
    monkeypatch.setattr(Y.yf, "Ticker", T)
    fx = Y.get_YFin_data_online("EURUSD=X", "2026-11-01", "2026-11-05")
    assert "1.12345" in fx and "1.12367" in fx
    st = Y.get_YFin_data_online("NVDA", "2026-11-01", "2026-11-05")
    assert "1.12" in st and "1.12345" not in st
