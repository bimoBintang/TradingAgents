"""Asset-class detection and data-vendor symbol mapping (forex support).

Single source of truth: the scheduler, data routing, ICT and TradingView
fallbacks all call these instead of guessing from the ticker string.
"""

from datetime import datetime, timezone
from typing import Optional

_FIAT = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK",
         "DKK", "SGD", "HKD", "MXN", "ZAR", "TRY", "PLN", "CNH"}
_METALS = {"XAU", "XAG"}

# shortcut: futures contracts as proxies for spot metals (yfinance has no clean spot
# feed); they carry a basis vs spot. Upgrade: pull candles from the MT5 terminal.
_METAL_PROXY = {"XAUUSD": "GC=F", "XAGUSD": "SI=F"}


def _forex_pair(ticker: str) -> Optional[str]:
    """'EUR/USD', 'eurusd=x' -> 'EURUSD' when it is a known fiat/metal pair, else None."""
    t = ticker.upper().strip().replace("=X", "")
    for ch in "/-_ ":
        t = t.replace(ch, "")
    if len(t) != 6 or not t.isalpha():
        return None
    base, quote = t[:3], t[3:]
    if base == quote or quote not in _FIAT:
        return None
    if base in _FIAT or base in _METALS:
        return t
    return None


def asset_class(ticker: str) -> str:
    """'forex' | 'crypto' | 'stock'."""
    if _forex_pair(ticker):
        return "forex"
    from tradingagents.graph.conditional_logic import is_crypto_ticker
    return "crypto" if is_crypto_ticker(ticker) else "stock"


def yf_symbol(ticker):
    """Symbol yfinance understands. Only forex/metals are rewritten; anything else is returned as-is."""
    if not isinstance(ticker, str):
        return ticker
    pair = _forex_pair(ticker)
    if not pair:
        return ticker
    return _METAL_PROXY.get(pair, f"{pair}=X")


def forex_market_open(now: Optional[datetime] = None) -> bool:
    """Sun 22:00 UTC -> Fri 22:00 UTC. shortcut: ignores session DST shifts and bank holidays."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc)
    wd, hr = now.weekday(), now.hour  # Mon=0 .. Sun=6
    if wd == 5:
        return False
    if wd == 4:
        return hr < 22
    if wd == 6:
        return hr >= 22
    return True
