"""Market data endpoints — OHLCV, Fibonacci, and Smart Money Concepts.

Serves price data, Fibonacci levels, and 6 SMC indicators
for the dashboard chart panel. Uses yfinance with hourly cache.
"""

import json
import time
import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    OHLCVCandle, OHLCVResponse, FibLevel, FibonacciResponse,
    FVGZone, FVGResponse, IFVGZone, IFVGResponse,
    SweepEvent, LiquiditySweepResponse,
    FlowCandle, OrderFlowSummary, OrderFlowResponse,
    VWAPPoint, AnchoredVWAPResponse,
    VolumeBucket, VolumeProfileResponse,
    PredictionMarketItem, PredictionEventItem, PredictionMarketsResponse,
)

logger = logging.getLogger("api.market_data")

router = APIRouter(prefix="/api/market-data", tags=["MarketData"])

VALID_INTERVALS = {"1d", "1h", "30m", "15m", "5m"}


# ── OHLCV Cache (hourly TTL via floor-to-hour key) ────────────────────

def _hour_key() -> int:
    """Return current UTC hour as an integer for cache busting."""
    return int(time.time() // 3600)


@lru_cache(maxsize=64)
def _fetch_ohlcv(ticker: str, interval: str, period: int, _ttl_key: int):
    """Cached yfinance download.  _ttl_key is the hour-bucket so the
    cache auto-expires every hour without manual invalidation."""
    # Map period (days) to yfinance period string
    if period <= 7:
        yf_period = "7d"
    elif period <= 30:
        yf_period = "1mo"
    elif period <= 90:
        yf_period = "3mo"
    elif period <= 180:
        yf_period = "6mo"
    elif period <= 365:
        yf_period = "1y"
    else:
        yf_period = "2y"

    df = yf.download(
        ticker,
        period=yf_period,
        interval=interval,
        progress=False,
        auto_adjust=True,
    )

    # Handle MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()
    return df


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/ohlcv", response_model=OHLCVResponse)
async def get_ohlcv(
    ticker: str = Query(..., description="Ticker symbol, e.g. NVDA or BTC-USD"),
    interval: str = Query("1d", description="Candle interval: 1d, 1h, 30m, 15m, 5m"),
    period: int = Query(200, ge=7, le=730, description="Lookback in calendar days"),
):
    """Return OHLCV candle data for chart rendering."""
    if interval not in VALID_INTERVALS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid interval '{interval}'. Must be one of {sorted(VALID_INTERVALS)}",
        )

    try:
        df = _fetch_ohlcv(ticker, interval, period, _hour_key())
    except Exception as e:
        logger.error(f"yfinance download failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail=f"Data source error: {e}")

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    candles = []
    for idx, row in df.iterrows():
        # Format time as yyyy-mm-dd for daily, full ISO for intraday
        if interval == "1d":
            time_str = idx.strftime("%Y-%m-%d")
        else:
            time_str = idx.strftime("%Y-%m-%dT%H:%M:%S")

        candles.append(OHLCVCandle(
            time=time_str,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row.get("Volume", 0)),
        ))

    return OHLCVResponse(
        ticker=ticker,
        interval=interval,
        candles=candles,
        count=len(candles),
    )


@router.get("/fibonacci", response_model=FibonacciResponse)
async def get_fibonacci(
    ticker: str = Query(..., description="Ticker symbol"),
    period: int = Query(90, ge=14, le=365, description="Lookback in calendar days"),
    extensions: bool = Query(True, description="Include extension levels"),
):
    """Compute Fibonacci retracement and extension levels for a ticker.

    Delegates the math to fibonacci_tools.get_fibonacci_levels and
    returns validated FibonacciResponse.
    """
    from tradingagents.agents.utils.fibonacci_tools import get_fibonacci_levels

    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        raw = get_fibonacci_levels.invoke({
            "symbol": ticker,
            "end_date": end_date,
            "lookback_days": period,
            "show_extensions": extensions,
        })
    except Exception as e:
        logger.error(f"Fibonacci computation failed for {ticker}: {e}")
        raise HTTPException(status_code=502, detail=f"Computation error: {e}")

    data = json.loads(raw) if isinstance(raw, str) else raw

    if data.get("status") != "ok":
        raise HTTPException(
            status_code=422,
            detail=data.get("message", "Fibonacci computation returned non-ok status"),
        )

    # Build validated response
    fib_levels = [
        FibLevel(
            label=lv["label"],
            ratio=lv["ratio"],
            price=lv["price"],
            type=lv["type"],
        )
        for lv in data["levels"]
    ]

    return FibonacciResponse(
        status=data["status"],
        symbol=data["symbol"],
        period=data["period"],
        data_points=data["data_points"],
        current_price=data["current_price"],
        swing_high=data["swing_high"],
        swing_low=data["swing_low"],
        swing_high_date=data.get("swing_high_date"),
        swing_low_date=data.get("swing_low_date"),
        trend_direction=data["trend_direction"],
        trend_confidence=data["trend_confidence"],
        is_uptrend=data["is_uptrend"],
        in_golden_zone=data["in_golden_zone"],
        levels=fib_levels,
    )


# ── SMC Endpoints ─────────────────────────────────────────────────────

def _invoke_smc_tool(tool_func, params: dict) -> dict:
    """Invoke an SMC tool and parse its JSON result."""
    raw = tool_func.invoke(params)
    data = json.loads(raw) if isinstance(raw, str) else raw
    if data.get("status") != "ok":
        raise HTTPException(
            status_code=422,
            detail=data.get("message", "SMC tool returned non-ok status"),
        )
    return data


@router.get("/fvg", response_model=FVGResponse)
async def get_fvg(
    ticker: str = Query(...), period: int = Query(90, ge=14, le=365),
):
    """Detect Fair Value Gaps."""
    from tradingagents.agents.utils.smc_tools import get_fair_value_gaps
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _invoke_smc_tool(get_fair_value_gaps, {
        "symbol": ticker, "end_date": end_date, "lookback_days": period,
    })
    return FVGResponse(
        status=data["status"], symbol=data["symbol"],
        fvgs=[FVGZone(**z) for z in data["fvgs"]],
    )


@router.get("/ifvg", response_model=IFVGResponse)
async def get_ifvg(
    ticker: str = Query(...), period: int = Query(90, ge=14, le=365),
):
    """Detect Inversion FVGs."""
    from tradingagents.agents.utils.smc_tools import get_inversion_fvgs
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _invoke_smc_tool(get_inversion_fvgs, {
        "symbol": ticker, "end_date": end_date, "lookback_days": period,
    })
    return IFVGResponse(
        status=data["status"], symbol=data["symbol"],
        ifvgs=[IFVGZone(**z) for z in data["ifvgs"]],
    )


@router.get("/liquidity-sweeps", response_model=LiquiditySweepResponse)
async def get_sweeps(
    ticker: str = Query(...), period: int = Query(90, ge=14, le=365),
):
    """Detect liquidity sweeps."""
    from tradingagents.agents.utils.smc_tools import get_liquidity_sweeps
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _invoke_smc_tool(get_liquidity_sweeps, {
        "symbol": ticker, "end_date": end_date, "lookback_days": period,
    })
    return LiquiditySweepResponse(
        status=data["status"], symbol=data["symbol"],
        sweeps=[SweepEvent(**s) for s in data["sweeps"]],
    )


@router.get("/order-flow", response_model=OrderFlowResponse)
async def get_flow(
    ticker: str = Query(...), period: int = Query(30, ge=7, le=180),
):
    """Estimate order flow delta."""
    from tradingagents.agents.utils.smc_tools import get_order_flow
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _invoke_smc_tool(get_order_flow, {
        "symbol": ticker, "end_date": end_date, "lookback_days": period,
    })
    return OrderFlowResponse(
        status=data["status"], symbol=data["symbol"],
        flow=[FlowCandle(**f) for f in data["flow"]],
        summary=OrderFlowSummary(**data["summary"]),
    )


@router.get("/vwap", response_model=AnchoredVWAPResponse)
async def get_vwap(
    ticker: str = Query(...), period: int = Query(90, ge=14, le=365),
    anchor_date: Optional[str] = Query(None, description="Anchor date yyyy-mm-dd"),
):
    """Compute anchored VWAP."""
    from tradingagents.agents.utils.smc_tools import get_anchored_vwap
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    params: dict = {"symbol": ticker, "end_date": end_date, "lookback_days": period}
    if anchor_date:
        params["anchor_date"] = anchor_date
    data = _invoke_smc_tool(get_anchored_vwap, params)
    return AnchoredVWAPResponse(
        status=data["status"], symbol=data["symbol"],
        anchor_date=data["anchor_date"], anchor_price=data["anchor_price"],
        vwap_values=[VWAPPoint(**v) for v in data["vwap_values"]],
        current_deviation_pct=data["current_deviation_pct"],
    )


@router.get("/volume-profile", response_model=VolumeProfileResponse)
async def get_vol_profile(
    ticker: str = Query(...), period: int = Query(90, ge=14, le=365),
    buckets: int = Query(50, ge=10, le=200),
):
    """Compute volume profile with POC/VAH/VAL."""
    from tradingagents.agents.utils.smc_tools import get_volume_profile
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = _invoke_smc_tool(get_volume_profile, {
        "symbol": ticker, "end_date": end_date, "lookback_days": period,
        "n_buckets": buckets,
    })
    return VolumeProfileResponse(
        status=data["status"], symbol=data["symbol"],
        poc_price=data["poc_price"], vah_price=data["vah_price"],
        val_price=data["val_price"],
        buckets=[VolumeBucket(**b) for b in data["buckets"]],
    )


# ── Polymarket Prediction Markets (Phase 14) ─────────────────────────

@router.get("/prediction-markets", response_model=PredictionMarketsResponse)
async def prediction_markets(
    query: str = Query(..., description="Search query (e.g. 'bitcoin', 'fed rate', 'nvidia')"),
    limit: int = Query(10, ge=1, le=20, description="Max events to return"),
):
    """Search active Polymarket prediction markets for crowd-sourced probability signals."""
    from tradingagents.agents.utils.polymarket_tools import get_prediction_markets as pm_tool
    data = _invoke_smc_tool(pm_tool, {"query": query, "limit": limit})
    events = []
    for ev in data.get("events", []):
        markets = [PredictionMarketItem(**m) for m in ev.get("markets", [])]
        events.append(PredictionEventItem(
            title=ev.get("title", ""), slug=ev.get("slug", ""),
            description=ev.get("description", ""),
            image=ev.get("image", ""), icon=ev.get("icon", ""),
            tags=ev.get("tags", []),
            volume=ev.get("volume", 0), liquidity=ev.get("liquidity", 0),
            start_date=ev.get("start_date", ""), end_date=ev.get("end_date", ""),
            markets=markets,
        ))
    return PredictionMarketsResponse(
        status=data.get("status", "ok"), query=query,
        count=len(events), events=events,
        message=data.get("message", ""),
    )
