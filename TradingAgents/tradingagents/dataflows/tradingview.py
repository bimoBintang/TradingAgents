"""
TradingView Dataflow Module.

Fetch technical indicators and summary recommendations directly from TradingView's scanner API
using tradingview-ta. Includes parameter validation, in-memory TTL caching, and retry logic.
"""

import time
import logging
from typing import Any, Dict, Optional, Tuple
from tradingview_ta import TA_Handler, Interval

logger = logging.getLogger(__name__)


class TradingViewFetchError(Exception):
    """Raised when fetching TradingView TA data fails after retries."""
    pass


class TradingViewRateLimitError(Exception):
    """Raised when TradingView rate limit is encountered."""
    pass


# ── Allowed Constants for Parameter Validation ──────────────────────────────
VALID_INTERVALS: Dict[str, str] = {
    "1m": Interval.INTERVAL_1_MINUTE,
    "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR,
    "2h": Interval.INTERVAL_2_HOURS,
    "4h": Interval.INTERVAL_4_HOURS,
    "1d": Interval.INTERVAL_1_DAY,
    "1w": Interval.INTERVAL_1_WEEK,
    "1W": Interval.INTERVAL_1_WEEK,
    "1mth": Interval.INTERVAL_1_MONTH,
    "1M": Interval.INTERVAL_1_MONTH,
}

VALID_SCREENERS = {"crypto", "america", "forex", "indonesia", "cfd", "crypto_futures"}


# ── In-Memory TTL Cache ─────────────────────────────────────────────────────
_CACHE: Dict[Tuple[str, str, str, str], Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS: float = 60.0  # 1 minute default cache


def _get_from_cache(cache_key: Tuple[str, str, str, str]) -> Optional[Dict[str, Any]]:
    """Retrieve data from cache if present and not expired."""
    if cache_key in _CACHE:
        timestamp, data = _CACHE[cache_key]
        if time.time() - timestamp < CACHE_TTL_SECONDS:
            logger.debug("[TradingView Cache] HIT for key %s", cache_key)
            return data
        else:
            logger.debug("[TradingView Cache] EXPIRED for key %s", cache_key)
            del _CACHE[cache_key]
    return None


def _set_in_cache(cache_key: Tuple[str, str, str, str], data: Dict[str, Any]) -> None:
    """Store data in cache with current timestamp."""
    _CACHE[cache_key] = (time.time(), data)


def clear_tradingview_cache() -> None:
    """Utility to clear all cached TradingView data."""
    _CACHE.clear()


# ── Parameter Validation Helper ─────────────────────────────────────────────
def validate_tradingview_params(
    symbol: str,
    screener: str = "crypto",
    exchange: str = "BINANCE",
    interval: str = "1h",
) -> Tuple[str, str, str, str]:
    """
    Validate and normalize parameters.
    Returns sanitized (symbol, screener, exchange, interval_code).
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string.")

    sanitized_symbol = symbol.strip().upper()
    sanitized_screener = screener.strip().lower() if screener else "crypto"
    sanitized_exchange = exchange.strip().upper() if exchange else "BINANCE"
    sanitized_interval = interval.strip() if interval else "1h"

    if sanitized_screener not in VALID_SCREENERS:
        logger.warning(
            "[TradingView] Unrecognized screener '%s', falling back to 'crypto'",
            sanitized_screener,
        )
        sanitized_screener = "crypto"

    if sanitized_interval not in VALID_INTERVALS:
        raise ValueError(
            f"Invalid interval '{interval}'. Valid options: {list(VALID_INTERVALS.keys())}"
        )

    interval_code = VALID_INTERVALS[sanitized_interval]
    return sanitized_symbol, sanitized_screener, sanitized_exchange, interval_code


# ── Core Fetch Function with Retry ─────────────────────────────────────────
def fetch_tradingview_ta(
    symbol: str,
    screener: str = "crypto",
    exchange: str = "BINANCE",
    interval: str = "1h",
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Fetch technical analysis summary and indicators from TradingView.

    Args:
        symbol: Ticker symbol (e.g., 'BTCUSDT', 'AAPL')
        screener: Market type ('crypto', 'america', 'forex', etc.)
        exchange: Exchange name ('BINANCE', 'NASDAQ', 'COINBASE', etc.)
        interval: Timeframe ('1m', '5m', '15m', '1h', '4h', '1d', '1w')
        max_retries: Number of retry attempts on network error
        backoff_factor: Exponential backoff delay factor in seconds
        use_cache: Enable/disable TTL caching

    Returns:
        Dict containing recommendation, buy/sell/neutral counts, and indicators dict.
    """
    sym, scr, exch, tv_interval = validate_tradingview_params(
        symbol, screener, exchange, interval
    )

    cache_key = (sym, scr, exch, interval)
    if use_cache:
        cached_result = _get_from_cache(cache_key)
        if cached_result is not None:
            return cached_result

    attempt = 0
    last_exception = None

    while attempt < max_retries:
        attempt += 1
        try:
            handler = TA_Handler(
                symbol=sym,
                screener=scr,
                exchange=exch,
                interval=tv_interval,
            )
            analysis = handler.get_analysis()

            result = {
                "symbol": sym,
                "screener": scr,
                "exchange": exch,
                "interval": interval,
                "recommendation": analysis.summary.get("RECOMMENDATION", "NEUTRAL"),
                "summary": {
                    "RECOMMENDATION": analysis.summary.get("RECOMMENDATION", "NEUTRAL"),
                    "BUY": analysis.summary.get("BUY", 0),
                    "SELL": analysis.summary.get("SELL", 0),
                    "NEUTRAL": analysis.summary.get("NEUTRAL", 0),
                },
                "oscillators": {
                    "RECOMMENDATION": analysis.oscillators.get("RECOMMENDATION", "NEUTRAL"),
                    "BUY": analysis.oscillators.get("BUY", 0),
                    "SELL": analysis.oscillators.get("SELL", 0),
                    "NEUTRAL": analysis.oscillators.get("NEUTRAL", 0),
                },
                "moving_averages": {
                    "RECOMMENDATION": analysis.moving_averages.get("RECOMMENDATION", "NEUTRAL"),
                    "BUY": analysis.moving_averages.get("BUY", 0),
                    "SELL": analysis.moving_averages.get("SELL", 0),
                    "NEUTRAL": analysis.moving_averages.get("NEUTRAL", 0),
                },
                "indicators": analysis.indicators or {},
            }

            if use_cache:
                _set_in_cache(cache_key, result)

            return result

        except Exception as exc:
            last_exception = exc
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower():
                logger.warning("[TradingView] Rate limit hit on attempt %d: %s", attempt, exc)
                if attempt == max_retries:
                    raise TradingViewRateLimitError(f"TradingView rate limit exceeded: {exc}") from exc
            else:
                logger.warning("[TradingView] Fetch failed on attempt %d/%d: %s", attempt, max_retries, exc)

            if attempt < max_retries:
                sleep_time = backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_time)

    raise TradingViewFetchError(
        f"Failed to fetch TradingView TA for {sym} on {exch} after {max_retries} attempts. Error: {last_exception}"
    ) from last_exception


def get_tradingview_indicators(
    symbol: str,
    screener: str = "crypto",
    exchange: str = "BINANCE",
    interval: str = "1h",
) -> Dict[str, Any]:
    """Helper entry point matching dataflows interface standards."""
    return fetch_tradingview_ta(symbol=symbol, screener=screener, exchange=exchange, interval=interval)
