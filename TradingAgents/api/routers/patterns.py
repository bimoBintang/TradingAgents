"""Chart pattern detection endpoint.

GET /api/market-data/patterns/{ticker}
Detects Head & Shoulders, Rising Wedge, and Falling Wedge patterns.
"""

import time
import logging
from typing import Optional

import pandas as pd
import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

from api.schemas import PatternResponse, ChartPattern, PatternPoint
from api.services.pattern_detector import PatternDetector

logger = logging.getLogger("api.patterns")

router = APIRouter(prefix="/api/market-data", tags=["Patterns"])

SUPPORTED_TIMEFRAMES = {"1d", "1h", "30m", "15m", "5m"}


def _hour_key() -> int:
    return int(time.time() // 3600)


@router.get("/patterns/{ticker}", response_model=PatternResponse)
async def detect_patterns(
    ticker: str,
    timeframe: str = Query("1d", description="Candle timeframe"),
    limit: int = Query(200, ge=50, le=500, description="Number of candles"),
    min_confidence: float = Query(0.5, ge=0.0, le=1.0, description="Minimum confidence filter"),
):
    """Detect chart patterns on OHLCV data for the given ticker."""

    # ── Validate timeframe ────────────────────────────────────────────
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Timeframe belum didukung, gunakan: {', '.join(sorted(SUPPORTED_TIMEFRAMES))}",
        )

    # ── Fetch OHLCV via yfinance ──────────────────────────────────────
    try:
        # Map limit (days) to yfinance period string
        if limit <= 7:
            yf_period = "7d"
        elif limit <= 30:
            yf_period = "1mo"
        elif limit <= 90:
            yf_period = "3mo"
        elif limit <= 180:
            yf_period = "6mo"
        elif limit <= 365:
            yf_period = "1y"
        else:
            yf_period = "2y"

        data = yf.download(
            ticker, period=yf_period, interval=timeframe,
            auto_adjust=True, progress=False,
        )
    except Exception as e:
        logger.error("yfinance download failed for %s: %s", ticker, e)
        raise HTTPException(
            status_code=503,
            detail=f"Exchange tidak dapat dijangkau: {e}",
        )

    if data is None or data.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker tidak ditemukan di exchange: {ticker}",
        )

    if len(data) < 50:
        raise HTTPException(
            status_code=422,
            detail=f"Data tidak cukup, minimal 50 candle. Diterima: {len(data)}",
        )

    # ── Build DataFrame with Unix-seconds timestamps ──────────────────
    # Flatten multi-level columns if present (yfinance v0.2+)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    df = pd.DataFrame({
        "timestamp": (data.index.astype("int64") // 10**9).astype(int),
        "open": data["Open"].values,
        "high": data["High"].values,
        "low": data["Low"].values,
        "close": data["Close"].values,
        "volume": data["Volume"].values,
    }).reset_index(drop=True)

    # ── Detect ────────────────────────────────────────────────────────
    detector = PatternDetector()
    raw_patterns = detector.detect_all(df, order=5)

    # ── Filter & sort ─────────────────────────────────────────────────
    patterns = [
        ChartPattern(
            type=p["type"],
            points=[PatternPoint(**pt) for pt in p["points"]],
            confidence=p["confidence"],
            direction=p["direction"],
        )
        for p in raw_patterns
        if p["confidence"] >= min_confidence
    ]
    patterns.sort(key=lambda p: p.confidence, reverse=True)

    return PatternResponse(
        ticker=ticker,
        timeframe=timeframe,
        candle_count=len(df),
        patterns=patterns,
        detected_at=int(time.time()),
    )
