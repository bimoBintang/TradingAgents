"""Shared mathematical utilities for Smart Money Concepts tools.

Single responsibility: provide reusable math functions for swing detection,
volume bucketing, order flow estimation, anchored VWAP, and OHLCV download.
Imported by smc_tools.py — never duplicated.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.signal import find_peaks

logger = logging.getLogger("tradingagents.tools.smc_utils")


# ── Data Structures ───────────────────────────────────────────────────

@dataclass
class SwingPoint:
    index: int
    price: float
    type: str  # 'high' or 'low'


@dataclass
class VolumeProfileResult:
    poc_price: float
    vah_price: float
    val_price: float
    total_volume: float
    buckets: List[dict]  # [{price_low, price_high, price_mid, volume, pct_of_total, is_value_area, is_poc}]


# ── OHLCV Download ───────────────────────────────────────────────────

def download_ohlcv(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Download OHLCV data from yfinance with MultiIndex and NaN handling."""
    df = yf.download(
        symbol,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=True,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df


# ── Swing Detection ──────────────────────────────────────────────────

def detect_swing_points(prices: np.ndarray, prominence_pct: float = 0.03) -> List[SwingPoint]:
    """Detect swing highs and lows using scipy.signal.find_peaks.

    Returns a list of SwingPoint sorted by index.
    Falls back to absolute extremes if find_peaks returns empty.
    """
    price_range = prices.max() - prices.min()
    if price_range == 0:
        price_range = prices.mean() * 0.01

    prominence = price_range * prominence_pct
    swings: List[SwingPoint] = []

    # Swing highs
    high_indices, _ = find_peaks(prices, prominence=prominence)
    if len(high_indices) == 0:
        high_indices = np.array([int(np.argmax(prices))])

    for idx in high_indices:
        swings.append(SwingPoint(index=int(idx), price=float(prices[idx]), type='high'))

    # Swing lows (peaks of inverted series)
    low_indices, _ = find_peaks(-prices, prominence=prominence)
    if len(low_indices) == 0:
        low_indices = np.array([int(np.argmin(prices))])

    for idx in low_indices:
        swings.append(SwingPoint(index=int(idx), price=float(prices[idx]), type='low'))

    swings.sort(key=lambda s: s.index)
    return swings


# ── Order Flow Estimation ─────────────────────────────────────────────

def estimate_order_flow(
    open_p: float, high: float, low: float, close: float, volume: float
) -> tuple:
    """Estimate buy/sell volume split from a single OHLCV candle.

    Returns (buy_vol, sell_vol, delta).
    """
    candle_range = high - low
    if candle_range <= 0:
        # Doji or zero-range candle — split 50/50
        buy_vol = volume * 0.5
        sell_vol = volume * 0.5
        return buy_vol, sell_vol, 0.0

    if close >= open_p:
        # Bullish candle
        buy_ratio = (close - low) / candle_range
        buy_vol = volume * buy_ratio
        sell_vol = volume - buy_vol
    else:
        # Bearish candle
        sell_ratio = (high - close) / candle_range
        sell_vol = volume * sell_ratio
        buy_vol = volume - sell_vol

    delta = buy_vol - sell_vol
    return float(buy_vol), float(sell_vol), float(delta)


# ── Anchored VWAP ────────────────────────────────────────────────────

def compute_anchored_vwap(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    volumes: np.ndarray, anchor_idx: int
) -> np.ndarray:
    """Compute VWAP anchored from a specific index.

    typical_price = (high + low + close) / 3
    vwap[i] = cumsum(tp * vol)[anchor:i+1] / cumsum(vol)[anchor:i+1]

    Returns array of vwap values (NaN before anchor).
    """
    n = len(closes)
    vwap = np.full(n, np.nan)

    typical_price = (highs + lows + closes) / 3.0
    cum_tp_vol = 0.0
    cum_vol = 0.0

    for i in range(anchor_idx, n):
        cum_tp_vol += typical_price[i] * volumes[i]
        cum_vol += volumes[i]
        if cum_vol > 0:
            vwap[i] = cum_tp_vol / cum_vol

    return vwap


# ── Volume Profile Bucketing ─────────────────────────────────────────

def bucket_volume_profile(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    volumes: np.ndarray, n_buckets: int = 50, value_area_pct: float = 0.70
) -> VolumeProfileResult:
    """Bin price range into N buckets and compute POC, VAH, VAL.

    Volume distribution: each candle's volume is assigned to the bucket
    containing its close price.

    Value Area: expand symmetrically from POC until cumulative volume
    reaches value_area_pct of total.
    """
    price_min = float(np.min(lows))
    price_max = float(np.max(highs))
    price_range = price_max - price_min

    if price_range <= 0:
        price_range = price_max * 0.01

    bucket_size = price_range / n_buckets
    bucket_volumes = np.zeros(n_buckets)

    # Distribute volume into buckets
    for i in range(len(closes)):
        bucket_idx = int((closes[i] - price_min) / bucket_size)
        bucket_idx = max(0, min(n_buckets - 1, bucket_idx))
        bucket_volumes[bucket_idx] += volumes[i]

    total_volume = float(np.sum(bucket_volumes))

    # POC — bucket with highest volume
    poc_idx = int(np.argmax(bucket_volumes))
    poc_price_low = price_min + poc_idx * bucket_size
    poc_price = poc_price_low + bucket_size / 2

    # Value Area — expand from POC
    included = set()
    included.add(poc_idx)
    cum_va_volume = bucket_volumes[poc_idx]
    target_volume = total_volume * value_area_pct

    lo = poc_idx - 1
    hi = poc_idx + 1

    while cum_va_volume < target_volume and (lo >= 0 or hi < n_buckets):
        vol_lo = bucket_volumes[lo] if lo >= 0 else -1
        vol_hi = bucket_volumes[hi] if hi < n_buckets else -1

        if vol_lo >= vol_hi and lo >= 0:
            included.add(lo)
            cum_va_volume += bucket_volumes[lo]
            lo -= 1
        elif hi < n_buckets:
            included.add(hi)
            cum_va_volume += bucket_volumes[hi]
            hi += 1
        else:
            break

    min_va_idx = min(included)
    max_va_idx = max(included)
    val_price = price_min + min_va_idx * bucket_size
    vah_price = price_min + (max_va_idx + 1) * bucket_size

    # Build buckets list
    buckets = []
    for b in range(n_buckets):
        b_low = price_min + b * bucket_size
        b_high = b_low + bucket_size
        pct = (bucket_volumes[b] / total_volume * 100) if total_volume > 0 else 0
        buckets.append({
            "price_low": round(b_low, 4),
            "price_high": round(b_high, 4),
            "price_mid": round(b_low + bucket_size / 2, 4),
            "volume": round(float(bucket_volumes[b]), 2),
            "pct_of_total": round(pct, 2),
            "is_value_area": b in included,
            "is_poc": b == poc_idx,
        })

    return VolumeProfileResult(
        poc_price=round(poc_price, 4),
        vah_price=round(vah_price, 4),
        val_price=round(val_price, 4),
        total_volume=round(total_volume, 2),
        buckets=buckets,
    )
