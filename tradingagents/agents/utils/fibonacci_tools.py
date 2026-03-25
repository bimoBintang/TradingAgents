"""Fibonacci Retracement & Extension tool for the LangGraph pipeline.

Computes Fibonacci levels from price data using scipy swing detection.
Single responsibility: take a ticker + date range → return structured
JSON with retracement levels, extension levels, and trend metadata.
"""

from langchain_core.tools import tool
from typing import Annotated
import json
import logging

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.signal import find_peaks

from tradingagents.agents.utils.advanced_tools import resilient_tool

logger = logging.getLogger("tradingagents.tools.fibonacci")

# ── Fibonacci Constants ───────────────────────────────────────────────

RETRACEMENT_RATIOS = {
    "0.0%": 0.0,
    "23.6%": 0.236,
    "38.2%": 0.382,
    "50.0%": 0.500,
    "61.8%": 0.618,
    "78.6%": 0.786,
    "100.0%": 1.0,
}

EXTENSION_RATIOS = {
    "127.2%": 1.272,
    "161.8%": 1.618,
    "261.8%": 2.618,
}


# ── Swing Detection ──────────────────────────────────────────────────

def _detect_swings(prices: np.ndarray, prominence_pct: float = 0.03):
    """Detect swing highs and lows using scipy find_peaks.

    Args:
        prices: 1-D array of close prices.
        prominence_pct: Minimum prominence as a fraction of price range.

    Returns:
        (swing_high_price, swing_high_idx, swing_low_price, swing_low_idx)
    """
    price_range = prices.max() - prices.min()
    if price_range == 0:
        price_range = prices.mean() * 0.01  # avoid zero-division

    prominence = price_range * prominence_pct

    # Swing highs: peaks in the price series
    high_indices, high_props = find_peaks(prices, prominence=prominence)

    # Swing lows: peaks in the *inverted* price series
    low_indices, low_props = find_peaks(-prices, prominence=prominence)

    # Pick the most prominent swing high
    if len(high_indices) > 0:
        best_high_idx = high_indices[np.argmax(high_props["prominences"])]
        swing_high = float(prices[best_high_idx])
        swing_high_pos = int(best_high_idx)
    else:
        # Fallback: absolute high
        best_high_idx = int(np.argmax(prices))
        swing_high = float(prices[best_high_idx])
        swing_high_pos = best_high_idx

    # Pick the most prominent swing low
    if len(low_indices) > 0:
        best_low_idx = low_indices[np.argmax(low_props["prominences"])]
        swing_low = float(prices[best_low_idx])
        swing_low_pos = int(best_low_idx)
    else:
        # Fallback: absolute low
        best_low_idx = int(np.argmin(prices))
        swing_low = float(prices[best_low_idx])
        swing_low_pos = best_low_idx

    return swing_high, swing_high_pos, swing_low, swing_low_pos


# ── Fibonacci Level Calculation ───────────────────────────────────────

def _compute_levels(swing_high: float, swing_low: float, is_uptrend: bool,
                    show_extensions: bool = True):
    """Compute Fibonacci retracement and extension price levels.

    In an uptrend, retracement goes from swing_high toward swing_low.
    In a downtrend, retracement goes from swing_low toward swing_high.
    """
    diff = swing_high - swing_low
    levels = []

    for label, ratio in RETRACEMENT_RATIOS.items():
        if is_uptrend:
            price = swing_high - diff * ratio
        else:
            price = swing_low + diff * ratio
        levels.append({
            "label": label,
            "ratio": ratio,
            "price": round(price, 4),
            "type": "retracement",
        })

    if show_extensions:
        for label, ratio in EXTENSION_RATIOS.items():
            if is_uptrend:
                price = swing_high + diff * (ratio - 1.0)
            else:
                price = swing_low - diff * (ratio - 1.0)
            levels.append({
                "label": label,
                "ratio": ratio,
                "price": round(price, 4),
                "type": "extension",
            })

    return levels


# ── Trend Confidence ──────────────────────────────────────────────────

def _trend_confidence(closes: np.ndarray) -> dict:
    """Estimate trend direction and confidence using SMA10/SMA30 crossover."""
    if len(closes) < 30:
        return {"direction": "neutral", "confidence": 0.0}

    sma10 = np.convolve(closes, np.ones(10) / 10, mode="valid")
    sma30 = np.convolve(closes, np.ones(30) / 30, mode="valid")

    # Align lengths — sma10 is longer than sma30 (by 20 elements)
    min_len = min(len(sma10), len(sma30))
    sma10_aligned = sma10[-min_len:]
    sma30_aligned = sma30[-min_len:]

    # Use the last 5 data points to determine crossover strength
    recent_diff = sma10_aligned[-5:] - sma30_aligned[-5:]
    avg_diff = float(np.mean(recent_diff))
    normalised = avg_diff / float(sma30_aligned[-1]) if sma30_aligned[-1] != 0 else 0.0

    if normalised > 0.005:
        direction = "bullish"
    elif normalised < -0.005:
        direction = "bearish"
    else:
        direction = "neutral"

    confidence = min(abs(normalised) * 100, 1.0)  # Cap at 1.0
    return {"direction": direction, "confidence": round(confidence, 4)}


# ── Main Tool ─────────────────────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=20)
def get_fibonacci_levels(
    symbol: Annotated[str, "Ticker symbol, e.g. NVDA or BTC-USD"],
    end_date: Annotated[str, "Reference date in yyyy-mm-dd format"],
    lookback_days: Annotated[int, "Number of trading days to look back"] = 90,
    show_extensions: Annotated[bool, "Include extension levels"] = True,
) -> str:
    """Compute Fibonacci retracement and extension levels for a given ticker.

    Uses scipy.signal.find_peaks for swing high/low detection with automatic
    fallback to absolute extremes. Returns structured JSON with levels,
    trend metadata, and golden-zone flag.

    Args:
        symbol: Ticker symbol (e.g. NVDA, BTC-USD, AAPL)
        end_date: End date for the analysis window (yyyy-mm-dd)
        lookback_days: Number of calendar days to look back (default 90)
        show_extensions: Whether to include 127.2%, 161.8%, 261.8% levels

    Returns:
        JSON string with fibonacci levels, swing points, and trend data.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)

    df = yf.download(
        symbol,
        start=start_dt.strftime("%Y-%m-%d"),
        end=(end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=True,
    )

    # Handle yfinance MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()

    if len(df) < 10:
        return json.dumps({
            "status": "insufficient_data",
            "symbol": symbol,
            "message": f"Only {len(df)} data points available, need at least 10.",
        })

    closes = df["Close"].values.astype(float)
    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)

    # Swing detection on highs/lows for better accuracy
    swing_high, sh_idx, _, _ = _detect_swings(highs)
    _, _, swing_low, sl_idx = _detect_swings(lows)

    # Ensure swing_high > swing_low (sanity check)
    if swing_high <= swing_low:
        swing_high = float(np.max(highs))
        swing_low = float(np.min(lows))
        sh_idx = int(np.argmax(highs))
        sl_idx = int(np.argmin(lows))

    # Determine trend: if swing high is more recent → uptrend
    is_uptrend = sh_idx > sl_idx

    trend = _trend_confidence(closes)
    levels = _compute_levels(swing_high, swing_low, is_uptrend, show_extensions)

    # Golden zone check: is current price between 38.2% and 61.8%?
    current_price = float(closes[-1])
    diff = swing_high - swing_low
    if is_uptrend:
        golden_low = swing_high - diff * 0.618
        golden_high = swing_high - diff * 0.382
    else:
        golden_low = swing_low + diff * 0.382
        golden_high = swing_low + diff * 0.618

    in_golden_zone = golden_low <= current_price <= golden_high

    result = {
        "status": "ok",
        "symbol": symbol,
        "period": f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}",
        "data_points": len(df),
        "current_price": round(current_price, 4),
        "swing_high": round(swing_high, 4),
        "swing_low": round(swing_low, 4),
        "swing_high_date": str(df.index[sh_idx].date()) if sh_idx < len(df) else None,
        "swing_low_date": str(df.index[sl_idx].date()) if sl_idx < len(df) else None,
        "trend_direction": trend["direction"],
        "trend_confidence": trend["confidence"],
        "is_uptrend": is_uptrend,
        "in_golden_zone": in_golden_zone,
        "levels": levels,
    }

    return json.dumps(result)
