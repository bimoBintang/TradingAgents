"""Smart Money Concepts (SMC) tools for the LangGraph pipeline.

6 @tool functions: FVG, IFVG, Liquidity Sweep, Order Flow, Anchored VWAP,
Volume Profile. All share math utilities from smc_utils.py.
"""

from langchain_core.tools import tool
from typing import Annotated, Optional
import json
import logging

import numpy as np
import pandas as pd

from tradingagents.agents.utils.advanced_tools import resilient_tool
from tradingagents.agents.utils.smc_utils import (
    download_ohlcv,
    detect_swing_points,
    estimate_order_flow,
    compute_anchored_vwap,
    bucket_volume_profile,
)

logger = logging.getLogger("tradingagents.tools.smc")


# ── Tool 1: Fair Value Gap ────────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_fair_value_gaps(
    symbol: Annotated[str, "Ticker symbol, e.g. NVDA or BTC-USD"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 90,
    min_gap_pct: Annotated[float, "Minimum gap size as fraction of price"] = 0.001,
) -> str:
    """Detect Fair Value Gaps (FVGs) — 3-candle imbalance zones.

    Bullish FVG: candle[i-2].high < candle[i].low (gap up)
    Bearish FVG: candle[i-2].low > candle[i].high (gap down)
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 3:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 3"})

    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    dates = [str(d.date()) for d in df.index]

    fvgs = []
    for i in range(2, len(df)):
        mid_price = (highs[i] + lows[i]) / 2
        if mid_price == 0:
            continue

        # Bullish FVG: previous candle's high < current candle's low
        if highs[i - 2] < lows[i]:
            gap_top = float(lows[i])
            gap_bottom = float(highs[i - 2])
            gap_size = gap_top - gap_bottom
            if gap_size / mid_price < min_gap_pct:
                continue

            # Fill tracking
            is_filled = False
            fill_pct = 0.0
            for j in range(i + 1, len(df)):
                if lows[j] <= gap_bottom:
                    is_filled = True
                    fill_pct = 1.0
                    break
                elif lows[j] < gap_top:
                    fill_pct = max(fill_pct, (gap_top - lows[j]) / gap_size)

            fvgs.append({
                "type": "bullish", "top": round(gap_top, 4),
                "bottom": round(gap_bottom, 4), "gap_size": round(gap_size, 4),
                "candle_date": dates[i - 1], "is_filled": is_filled,
                "fill_pct": round(fill_pct, 4),
            })

        # Bearish FVG: previous candle's low > current candle's high
        if lows[i - 2] > highs[i]:
            gap_top = float(lows[i - 2])
            gap_bottom = float(highs[i])
            gap_size = gap_top - gap_bottom
            if gap_size / mid_price < min_gap_pct:
                continue

            is_filled = False
            fill_pct = 0.0
            for j in range(i + 1, len(df)):
                if highs[j] >= gap_top:
                    is_filled = True
                    fill_pct = 1.0
                    break
                elif highs[j] > gap_bottom:
                    fill_pct = max(fill_pct, (highs[j] - gap_bottom) / gap_size)

            fvgs.append({
                "type": "bearish", "top": round(gap_top, 4),
                "bottom": round(gap_bottom, 4), "gap_size": round(gap_size, 4),
                "candle_date": dates[i - 1], "is_filled": is_filled,
                "fill_pct": round(fill_pct, 4),
            })

    return json.dumps({"status": "ok", "symbol": symbol, "fvgs": fvgs})


# ── Tool 2: Inversion FVG ────────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_inversion_fvgs(
    symbol: Annotated[str, "Ticker symbol"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 90,
) -> str:
    """Detect Inversion FVGs — FVGs fully breached and flipped in bias.

    A bullish FVG breached (close < bottom) → inverts to bearish resistance.
    A bearish FVG breached (close > top) → inverts to bullish support.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 3:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 3"})

    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    dates = [str(d.date()) for d in df.index]

    ifvgs = []

    for i in range(2, len(df)):
        # Bullish FVG
        if highs[i - 2] < lows[i]:
            gap_top = float(lows[i])
            gap_bottom = float(highs[i - 2])
            # Check for full breach (close below bottom) → inversion
            for j in range(i + 1, len(df)):
                if closes[j] < gap_bottom:
                    ifvgs.append({
                        "original_type": "bullish", "inverted_type": "bearish",
                        "top": round(gap_top, 4), "bottom": round(gap_bottom, 4),
                        "original_date": dates[i - 1], "breach_date": dates[j],
                    })
                    break

        # Bearish FVG
        if lows[i - 2] > highs[i]:
            gap_top = float(lows[i - 2])
            gap_bottom = float(highs[i])
            for j in range(i + 1, len(df)):
                if closes[j] > gap_top:
                    ifvgs.append({
                        "original_type": "bearish", "inverted_type": "bullish",
                        "top": round(gap_top, 4), "bottom": round(gap_bottom, 4),
                        "original_date": dates[i - 1], "breach_date": dates[j],
                    })
                    break

    return json.dumps({"status": "ok", "symbol": symbol, "ifvgs": ifvgs})


# ── Tool 3: Liquidity Sweep ──────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_liquidity_sweeps(
    symbol: Annotated[str, "Ticker symbol"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 90,
    threshold_pct: Annotated[float, "Min sweep overshoot as fraction"] = 0.001,
) -> str:
    """Detect liquidity sweeps — stop-hunts beyond swing highs/lows.

    Buy-side sweep: wick above swing high, close back below.
    Sell-side sweep: wick below swing low, close back above.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 10:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 10"})

    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    dates = [str(d.date()) for d in df.index]

    swings = detect_swing_points(closes)
    sweeps = []

    for swing in swings:
        si = swing.index
        sp = swing.price

        # Check candles after the swing
        for j in range(si + 1, min(si + 30, len(df))):
            if swing.type == 'high':
                # Buy-side sweep: wick above swing high, close below
                sweep_threshold = sp * (1 + threshold_pct)
                if highs[j] > sweep_threshold and closes[j] < sp:
                    # Reversal confirmation: next 3 candles
                    reversal = False
                    if j + 3 < len(df):
                        reversal = all(closes[j + k] < sp for k in range(1, 4))
                    sweeps.append({
                        "type": "buy_side",
                        "swing_price": round(sp, 4),
                        "sweep_price": round(float(highs[j]), 4),
                        "sweep_date": dates[j],
                        "reversal_confirmed": reversal,
                    })
                    break

            elif swing.type == 'low':
                # Sell-side sweep: wick below swing low, close above
                sweep_threshold = sp * (1 - threshold_pct)
                if lows[j] < sweep_threshold and closes[j] > sp:
                    reversal = False
                    if j + 3 < len(df):
                        reversal = all(closes[j + k] > sp for k in range(1, 4))
                    sweeps.append({
                        "type": "sell_side",
                        "swing_price": round(sp, 4),
                        "sweep_price": round(float(lows[j]), 4),
                        "sweep_date": dates[j],
                        "reversal_confirmed": reversal,
                    })
                    break

    return json.dumps({"status": "ok", "symbol": symbol, "sweeps": sweeps})


# ── Tool 4: Order Flow Delta ─────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_order_flow(
    symbol: Annotated[str, "Ticker symbol"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 30,
) -> str:
    """Estimate order flow delta (buy vs sell pressure) per candle.

    Approximation from OHLCV: uses candle body position within range.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 5:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 5"})

    opens = df["Open"].values.astype(float)
    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)
    dates = [str(d.date()) for d in df.index]

    flow = []
    cum_delta = 0.0

    for i in range(len(df)):
        buy_vol, sell_vol, delta = estimate_order_flow(
            opens[i], highs[i], lows[i], closes[i], volumes[i]
        )
        cum_delta += delta
        flow.append({
            "date": dates[i],
            "delta": round(delta, 2),
            "cumulative_delta": round(cum_delta, 2),
            "buy_vol": round(buy_vol, 2),
            "sell_vol": round(sell_vol, 2),
        })

    net_delta = cum_delta
    avg_delta = net_delta / len(flow) if flow else 0
    if net_delta > 0:
        pressure = "buying"
    elif net_delta < 0:
        pressure = "selling"
    else:
        pressure = "neutral"

    summary = {
        "net_delta": round(net_delta, 2),
        "avg_delta": round(avg_delta, 2),
        "pressure": pressure,
    }

    return json.dumps({"status": "ok", "symbol": symbol, "flow": flow, "summary": summary})


# ── Tool 5: Anchored VWAP ────────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=20)
def get_anchored_vwap(
    symbol: Annotated[str, "Ticker symbol"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 90,
    anchor_date: Annotated[Optional[str], "Anchor date yyyy-mm-dd, auto if None"] = None,
) -> str:
    """Compute VWAP anchored to a pivot point.

    Auto-anchor: most recent significant swing low (uptrend) or
    swing high (downtrend) detected by find_peaks.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 10:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 10"})

    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)
    dates = [str(d.date()) for d in df.index]

    # Determine anchor index
    if anchor_date:
        anchor_dt = pd.Timestamp(anchor_date)
        # Find closest date
        idx_diffs = abs(df.index - anchor_dt)
        anchor_idx = int(idx_diffs.argmin())
    else:
        # Auto-anchor: determine trend direction
        sma_short = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        sma_long = np.mean(closes[-30:]) if len(closes) >= 30 else np.mean(closes)
        is_uptrend = sma_short > sma_long

        swings = detect_swing_points(closes)
        target_type = 'low' if is_uptrend else 'high'
        matching = [s for s in swings if s.type == target_type]

        if matching:
            anchor_idx = matching[-1].index  # Most recent
        else:
            anchor_idx = 0  # Fallback to start

    anchor_price = float(closes[anchor_idx])

    # Compute VWAP
    vwap_values = compute_anchored_vwap(highs, lows, closes, volumes, anchor_idx)

    result_values = []
    for i in range(anchor_idx, len(df)):
        vwap_val = float(vwap_values[i])
        price = float(closes[i])
        dev_pct = ((price - vwap_val) / vwap_val * 100) if vwap_val > 0 else 0.0
        result_values.append({
            "date": dates[i],
            "vwap": round(vwap_val, 4),
            "price": round(price, 4),
            "deviation_pct": round(dev_pct, 4),
        })

    current_dev = result_values[-1]["deviation_pct"] if result_values else 0.0

    return json.dumps({
        "status": "ok", "symbol": symbol,
        "anchor_date": dates[anchor_idx],
        "anchor_price": round(anchor_price, 4),
        "vwap_values": result_values,
        "current_deviation_pct": round(current_dev, 4),
    })


# ── Tool 6: Volume Profile ───────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_volume_profile(
    symbol: Annotated[str, "Ticker symbol"],
    end_date: Annotated[str, "Reference date yyyy-mm-dd"],
    lookback_days: Annotated[int, "Calendar days to look back"] = 90,
    n_buckets: Annotated[int, "Number of price buckets"] = 50,
    value_area_pct: Annotated[float, "Value area percentage"] = 0.70,
) -> str:
    """Compute volume profile — price-at-volume distribution.

    Returns POC (Point of Control), VAH (Value Area High),
    VAL (Value Area Low), and per-bucket volume data.
    """
    end_dt = pd.Timestamp(end_date)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)
    df = download_ohlcv(symbol, start_dt.strftime("%Y-%m-%d"),
                        (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))

    if len(df) < 5:
        return json.dumps({"status": "insufficient_data", "symbol": symbol,
                           "message": f"Only {len(df)} candles, need >= 5"})

    highs = df["High"].values.astype(float)
    lows = df["Low"].values.astype(float)
    closes = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)

    profile = bucket_volume_profile(highs, lows, closes, volumes, n_buckets, value_area_pct)

    return json.dumps({
        "status": "ok", "symbol": symbol,
        "poc_price": profile.poc_price,
        "vah_price": profile.vah_price,
        "val_price": profile.val_price,
        "total_volume": profile.total_volume,
        "buckets": profile.buckets,
    })
