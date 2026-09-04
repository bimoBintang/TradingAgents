"""Public (unauthenticated) OHLCV fetch from any ccxt-supported exchange.

Used to source live chart candles from the SAME exchange a user's live
broker actually executes on. Previously ChartPanel always used yfinance —
real data, but for crypto it's Yahoo's composite/delayed price, which can
visibly diverge from what the bot actually traded at on Binance/Bitget/etc.
No API key needed here: OHLCV is public market data on every exchange
ccxt supports, so this never touches user credentials.
"""

import logging
import threading
from typing import Dict, List

import ccxt

logger = logging.getLogger(__name__)

# One shared, unauthenticated ccxt client per exchange — cheap to keep
# around (no session/connection state worth tearing down), reused across
# every ws_ohlcv tick and every user watching that exchange.
_clients: Dict[str, "ccxt.Exchange"] = {}
_lock = threading.Lock()


def _get_client(exchange_id: str) -> "ccxt.Exchange":
    with _lock:
        client = _clients.get(exchange_id)
        if client is None:
            exchange_class = getattr(ccxt, exchange_id, None)
            if exchange_class is None:
                raise ValueError(f"Exchange '{exchange_id}' not supported by ccxt.")
            client = exchange_class({"enableRateLimit": True})
            _clients[exchange_id] = client
        return client


def normalize_symbol(ticker: str, quote: str = "USDT") -> str:
    """'BTCUSDT' -> 'BTC/USDT'; 'BTC/USDT' unchanged; 'BTC-USD' -> 'BTC/USD'."""
    if "/" in ticker:
        return ticker
    if "-" in ticker:
        base, q = ticker.split("-", 1)
        return f"{base}/{q}"
    ticker_upper = ticker.upper()
    if ticker_upper.endswith(quote) and len(ticker_upper) > len(quote):
        return f"{ticker[:-len(quote)]}/{quote}"
    return f"{ticker}/{quote}"


def fetch_ohlcv(
    exchange_id: str,
    ticker: str,
    timeframe: str = "1h",
    limit: int = 200,
    quote: str = "USDT",
) -> List[dict]:
    """Fetch recent candles for `ticker` from `exchange_id`, oldest first.

    Returns the same {time, open, high, low, close, volume} shape the
    existing yfinance-backed OHLCVResponse already uses, so the frontend
    doesn't need two candle formats.

    Raises whatever ccxt raises (network error, unsupported symbol, bad
    exchange id) — callers (ws_ohlcv) are expected to catch and log this,
    not treat it as fatal, since the yfinance path keeps working either way.
    """
    client = _get_client(exchange_id)
    symbol = normalize_symbol(ticker, quote=quote)
    raw = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return [
        {
            "time": client.iso8601(ts).split(".")[0],
            "open": o, "high": h, "low": low, "close": c, "volume": v,
        }
        for ts, o, h, low, c, v in raw
    ]
