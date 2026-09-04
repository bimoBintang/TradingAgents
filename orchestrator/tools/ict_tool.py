"""
Inner Circle Trader (ICT / Smart Money Concepts) Core Engine & Analysis Tool.

Provides quantitative detection for:
1. Displacement Ratio & Order Blocks (OB) [HIGH vs MEDIUM strength]
2. Fair Value Gaps (FVG) [UNFILLED, PARTIALLY_FILLED 50%, FULLY_FILLED 100%]
3. Liquidity Sweeps (BSL / SSL Wick Penetration + Reversal Close)
4. Optimal Trade Entry (OTE) Fib Zones (61.8% - 78.6%)
"""

import math
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import pandas as pd

from orchestrator.sdk.agent_builder import tool

logger = logging.getLogger(__name__)


@dataclass
class ICTConfig:
    """Configurable parameters for ICT Smart Money Concepts detection."""
    high_displacement_threshold: float = 2.0     # High Strength OB
    medium_displacement_threshold: float = 1.5   # Medium Strength OB
    wick_penetration_pct: float = 0.001          # 0.10% Wick Sweep
    fvg_partial_fill_pct: float = 0.50           # 50% Consequent Encroachment
    reversal_window_candles: int = 2             # Reversal within 2 candles
    min_oos_trade_count: int = 15                # Min OOS trades for backtest validity


DEFAULT_ICT_CONFIG = ICTConfig()


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Calculate Average True Range (ATR) over period."""
    if len(closes) < 2:
        return [1.0] * len(closes)

    tr_list = []
    for i in range(len(closes)):
        if i == 0:
            tr_list.append(highs[i] - lows[i])
        else:
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            tr_list.append(max(tr1, tr2, tr3))

    atr_list = []
    curr_atr = sum(tr_list[:period]) / period if len(tr_list) >= period else sum(tr_list) / len(tr_list)
    for i in range(len(tr_list)):
        if i < period:
            atr_list.append(curr_atr)
        else:
            curr_atr = (curr_atr * (period - 1) + tr_list[i]) / period
            atr_list.append(curr_atr)

    return atr_list


def detect_fair_value_gaps(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    config: ICTConfig = DEFAULT_ICT_CONFIG,
) -> List[Dict[str, Any]]:
    """
    Detect Bullish and Bearish Fair Value Gaps (FVG) and track 50% CE fill status.
    """
    fvgs = []
    n = len(closes)
    if n < 3:
        return fvgs

    for i in range(2, n):
        is_bullish = highs[i - 2] < lows[i]
        is_bearish = lows[i - 2] > highs[i]
        if not (is_bullish or is_bearish):
            continue

        if is_bullish:
            gap_bottom, gap_top = highs[i - 2], lows[i]
        else:
            gap_bottom, gap_top = highs[i], lows[i - 2]

        gap_size = gap_top - gap_bottom
        midpoint_ce = gap_bottom + (gap_size * config.fvg_partial_fill_pct)

        # Fill status is resolved by scanning EVERY bar after the gap
        # formed, not by peeking at one arbitrary bar.
        #
        # This previously read `lows[-1]` / `highs[-1]` — the last bar of
        # the entire series — regardless of which bar the gap formed on.
        # Two separate defects: (a) a gap at index 5 in a 200-bar series
        # was judged against bar 199, which is lookahead; (b) even live it
        # only inspected ONE bar, so a gap that was traded through at bar
        # 20 and left behind by bar 199 was still reported UNFILLED. Fill
        # status was effectively random, and it feeds ict_bias, which the
        # LLM agents read as evidence. (TVExecutionGuard also consumes
        # ict_bias by design, but as of this writing that guard is not
        # wired into any execution path — see its own module.)
        fill_status = "UNFILLED"
        partial_idx: Optional[int] = None
        full_idx: Optional[int] = None

        for j in range(i + 1, n):
            if is_bullish:
                touched_ce = lows[j] <= midpoint_ce
                touched_full = lows[j] <= gap_bottom
            else:
                touched_ce = highs[j] >= midpoint_ce
                touched_full = highs[j] >= gap_top

            if partial_idx is None and touched_ce:
                partial_idx = j
                fill_status = "PARTIALLY_FILLED"
            if touched_full:
                full_idx = j
                fill_status = "FULLY_FILLED"
                break

        fvgs.append({
            "type": "BULLISH_FVG" if is_bullish else "BEARISH_FVG",
            "index": i,
            "gap_top": round(gap_top, 2),
            "gap_bottom": round(gap_bottom, 2),
            "gap_size_pct": round((gap_size / closes[i] * 100.0), 4) if closes[i] else 0.0,
            "midpoint_ce": round(midpoint_ce, 2),
            "fill_status": fill_status,
            # Bars elapsed until each fill level — None if never reached
            # within the supplied window. Consumed by the ICT measurement
            # harness to compute empirical fill rates and time-to-fill.
            "bars_to_partial_fill": (partial_idx - i) if partial_idx is not None else None,
            "bars_to_full_fill": (full_idx - i) if full_idx is not None else None,
            # Bars of data available after formation. A gap formed near the
            # end of the window has had little chance to fill — excluding
            # those is essential or the measured fill rate is biased down.
            "bars_observed": n - 1 - i,
        })

    return fvgs


def detect_order_blocks(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    atr_list: List[float],
    config: ICTConfig = DEFAULT_ICT_CONFIG,
) -> List[Dict[str, Any]]:
    """
    Detect Order Blocks (OB) and assign Strength via Displacement Ratio.
    """
    obs = []
    n = len(closes)
    if n < 4:
        return obs

    for i in range(1, n - 2):
        body_next = abs(closes[i + 1] - opens[i + 1])
        atr_val = atr_list[i + 1] if atr_list[i + 1] > 0 else 1.0
        displacement = body_next / atr_val

        # Strength assignment
        if displacement >= config.high_displacement_threshold:
            strength = "HIGH"
        elif displacement >= config.medium_displacement_threshold:
            strength = "MEDIUM"
        else:
            continue  # Ignore weak displacement

        # Bullish OB: Last down-close candle before strong upward displacement
        if closes[i] < opens[i] and closes[i + 1] > opens[i + 1] and closes[i + 1] > highs[i]:
            obs.append({
                "type": "BULLISH_OB",
                "index": i,
                "ob_top": round(highs[i], 2),
                "ob_bottom": round(lows[i], 2),
                "displacement_ratio": round(displacement, 2),
                "strength": strength,
            })

        # Bearish OB: Last up-close candle before strong downward displacement
        elif closes[i] > opens[i] and closes[i + 1] < opens[i + 1] and closes[i + 1] < lows[i]:
            obs.append({
                "type": "BEARISH_OB",
                "index": i,
                "ob_top": round(highs[i], 2),
                "ob_bottom": round(lows[i], 2),
                "displacement_ratio": round(displacement, 2),
                "strength": strength,
            })

    return obs


def detect_liquidity_sweeps(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    config: ICTConfig = DEFAULT_ICT_CONFIG,
) -> List[Dict[str, Any]]:
    """
    Detect Liquidity Sweeps (BSL / SSL Wick Penetration + Reversal Close).
    """
    sweeps = []
    n = len(closes)
    if n < 10:
        return sweeps

    # Find swing highs and swing lows
    recent_highs = highs[-10:-2]
    recent_lows = lows[-10:-2]
    swing_high = max(recent_highs)
    swing_low = min(recent_lows)

    curr_high = highs[-1]
    curr_low = lows[-1]
    curr_close = closes[-1]

    # BSL Sweep: High penetrates swing high by > 0.1%, but Close returns below swing high
    if curr_high > swing_high * (1.0 + config.wick_penetration_pct) and curr_close < swing_high:
        sweeps.append({
            "type": "BUY_SIDE_LIQUIDITY_SWEEP",
            "level": round(swing_high, 2),
            "wick_high": round(curr_high, 2),
            "close_price": round(curr_close, 2),
            "swept": True,
        })

    # SSL Sweep: Low penetrates swing low by > 0.1%, but Close returns above swing low
    if curr_low < swing_low * (1.0 - config.wick_penetration_pct) and curr_close > swing_low:
        sweeps.append({
            "type": "SELL_SIDE_LIQUIDITY_SWEEP",
            "level": round(swing_low, 2),
            "wick_low": round(curr_low, 2),
            "close_price": round(curr_close, 2),
            "swept": True,
        })

    return sweeps


@tool(name="analyze_ict_concepts", category="technical")
def analyze_ict_concepts(
    ticker: str = "BTCUSDT",
    prices: Optional[List[float]] = None,
    opens: Optional[List[float]] = None,
    highs: Optional[List[float]] = None,
    lows: Optional[List[float]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Perform quantitative Inner Circle Trader (ICT / SMC) Smart Money analysis.
    Identifies Fair Value Gaps, Order Blocks, Liquidity Sweeps, and OTE Fib Zones.

    Pass REAL `opens`/`highs`/`lows` alongside `prices` (closes) whenever
    possible. Every concept this engine detects is defined by wick and body
    geometry, so it is only as meaningful as the candles it is given:

      - FVG needs true gaps between candle extremes
      - Order Block strength = body / ATR, i.e. real body sizes
      - Liquidity sweeps are wick penetrations, by definition

    The returned `data_quality` field states which regime produced the
    result; anything other than REAL_OHLC should not drive sizing.
    """
    ticker_clean = ticker.strip().upper()
    logger.info("[ICTEngine] Running ICT Smart Money analysis for %s", ticker_clean)

    warnings: List[str] = []

    has_real_ohlc = (
        prices and opens and highs and lows
        and len(prices) >= 15
        and len(opens) == len(highs) == len(lows) == len(prices)
    )

    if has_real_ohlc:
        closes = list(prices)
        opens = list(opens)
        highs = list(highs)
        lows = list(lows)
        data_quality = "REAL_OHLC"
    elif prices and len(prices) >= 15:
        # Closes only. Open/High/Low are DERIVED, not observed — every bar
        # gets an identical 0.4% range, which makes displacement ratios
        # near-constant and turns "FVG" into nothing more than "price rose
        # >0.4% over two bars". Kept for backward compatibility, but the
        # caller is told plainly not to trust structure from it.
        closes = list(prices)
        opens = [p * 0.999 for p in prices]
        highs = [p * 1.002 for p in prices]
        lows = [p * 0.998 for p in prices]
        data_quality = "SYNTHETIC_OHLC_FROM_CLOSES"
        warnings.append(
            "Open/High/Low were synthesized from close prices with fixed multipliers. "
            "Fair Value Gaps, Order Block strength and Liquidity Sweeps are all defined "
            "by candle geometry, so these results describe the synthesis, not the market. "
            "Pass real opens/highs/lows."
        )
    else:
        # No market data at all — a deterministic sine wave. Useful only as
        # a smoke test that the pipeline runs.
        base_price = 60000.0
        closes = [base_price + (i * 20.0) + (math.sin(i / 2.0) * 150.0) for i in range(40)]
        opens = [closes[i] - 10.0 if i % 2 == 0 else closes[i] + 10.0 for i in range(40)]
        highs = [max(opens[i], closes[i]) + 25.0 for i in range(40)]
        lows = [min(opens[i], closes[i]) - 25.0 for i in range(40)]
        data_quality = "SIMULATED_NO_DATA"
        warnings.append(
            "No price data supplied — this analysis ran on a generated sine wave and "
            "describes nothing about the real market. Do NOT use it for any decision."
        )
        logger.warning(
            "[ICTEngine] %s analyzed with NO market data (sine-wave placeholder).",
            ticker_clean,
        )

    cfg = DEFAULT_ICT_CONFIG
    atr_list = calculate_atr(highs, lows, closes, period=14)

    fvgs = detect_fair_value_gaps(opens, highs, lows, closes, cfg)
    obs = detect_order_blocks(opens, highs, lows, closes, atr_list, cfg)
    sweeps = detect_liquidity_sweeps(highs, lows, closes, cfg)

    # Calculate Optimal Trade Entry (OTE) Fib 61.8% - 78.6%
    swing_min = min(lows[-20:])
    swing_max = max(highs[-20:])
    range_diff = swing_max - swing_min
    fib_618 = swing_max - (range_diff * 0.618)
    fib_786 = swing_max - (range_diff * 0.786)
    curr_price = closes[-1]
    in_ote = fib_786 <= curr_price <= fib_618

    # Determine Overall ICT Bias
    unfilled_bull_fvg = any(f["type"] == "BULLISH_FVG" and f["fill_status"] != "FULLY_FILLED" for f in fvgs)
    unfilled_bear_fvg = any(f["type"] == "BEARISH_FVG" and f["fill_status"] != "FULLY_FILLED" for f in fvgs)
    has_high_bull_ob = any(o["type"] == "BULLISH_OB" and o["strength"] == "HIGH" for o in obs)
    has_high_bear_ob = any(o["type"] == "BEARISH_OB" and o["strength"] == "HIGH" for o in obs)

    if has_high_bull_ob or unfilled_bull_fvg:
        ict_bias = "BULLISH"
    elif has_high_bear_ob or unfilled_bear_fvg:
        ict_bias = "BEARISH"
    else:
        ict_bias = "NEUTRAL"

    return {
        "ticker": ticker_clean,
        "current_price": round(curr_price, 2),
        "ict_bias": ict_bias,
        "fair_value_gaps": fvgs[-5:],  # Return top 5 recent FVGs
        "order_blocks": obs[-5:],       # Return top 5 recent OBs
        "liquidity_sweeps": sweeps,
        "ote_zone": {
            "fib_618": round(fib_618, 2),
            "fib_786": round(fib_786, 2),
            "in_ote_zone": in_ote,
        },
        # Callers must be able to tell a genuine read from a placeholder.
        # Never omit these two. (TVExecutionGuard is the intended consumer
        # of ict_bias for blocking/resizing, but it is currently not
        # invoked from any execution path.)
        "data_quality": data_quality,
        "warnings": warnings,
    }
