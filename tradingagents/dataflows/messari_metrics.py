"""Messari timeseries metrics — ROI, ATH, and on-chain timeseries."""

import logging
from typing import Optional

from .messari_common import make_request, ticker_to_slug, MessariAPIError

logger = logging.getLogger("dataflows.messari.metrics")


def get_timeseries(
    ticker: str,
    metric: str = "price",
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
) -> str:
    """Fetch timeseries metric data for an asset.

    Parameters
    ----------
    ticker  : Asset ticker (e.g. "BTC", "ETH-USD")
    metric  : Metric slug (e.g. "price", "txn.cnt", "act.addr.cnt",
              "nvt", "fees", "mcap.dom")
    start   : ISO date string (e.g. "2024-01-01")
    end     : ISO date string
    interval: "1d", "1w", etc.
    """
    slug = ticker_to_slug(ticker)
    params = {"interval": interval}
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    try:
        data = make_request(f"assets/{slug}/metrics/{metric}/time-series", params=params)
    except MessariAPIError as e:
        return f"[Messari] Timeseries error for {ticker}/{metric}: {e}"

    if not isinstance(data, dict):
        return f"[Messari] Unexpected response for {ticker}/{metric}"

    values = data.get("values", [])
    schema = data.get("parameters", {})

    if not values:
        return f"[Messari] No timeseries data for {ticker}/{metric}"

    lines = [
        f"=== Messari Timeseries: {ticker} / {metric} ===",
        f"Interval: {interval} | Points: {len(values)}",
    ]

    # Show last 10 data points
    for row in values[-10:]:
        if len(row) >= 2:
            lines.append(f"  {row[0]} → {row[1]}")

    return "\n".join(lines)


def get_roi(ticker: str) -> str:
    """Fetch ROI data for an asset (1d, 7d, 30d, 1y, ATH)."""
    slug = ticker_to_slug(ticker)
    try:
        data = make_request(f"assets/{slug}/metrics")
    except MessariAPIError as e:
        return f"[Messari] ROI error for {ticker}: {e}"

    roi = data.get("roi_data", {})
    lines = [
        f"=== Messari ROI: {ticker} ===",
        f"24h: {roi.get('percent_change_last_24_hours', 'N/A')}%",
        f"7d:  {roi.get('percent_change_last_1_week', 'N/A')}%",
        f"30d: {roi.get('percent_change_last_1_month', 'N/A')}%",
        f"1y:  {roi.get('percent_change_last_1_year', 'N/A')}%",
        f"QTD: {roi.get('percent_change_quarter_to_date', 'N/A')}%",
        f"YTD: {roi.get('percent_change_year_to_date', 'N/A')}%",
    ]
    return "\n".join(lines)


def get_ath(ticker: str) -> str:
    """Fetch All-Time High data for an asset."""
    slug = ticker_to_slug(ticker)
    try:
        data = make_request(f"assets/{slug}/metrics")
    except MessariAPIError as e:
        return f"[Messari] ATH error for {ticker}: {e}"

    ath = data.get("all_time_high", {})
    market = data.get("market_data", {})
    current_price = market.get("price_usd", 0)
    ath_price = ath.get("price", 0)
    pct_down = ath.get("percent_down", 0)

    lines = [
        f"=== Messari ATH: {ticker} ===",
        f"ATH Price: ${ath_price:,.2f}" if isinstance(ath_price, (int, float)) else f"ATH: {ath_price}",
        f"ATH Date: {ath.get('at', 'N/A')}",
        f"Current: ${current_price:,.2f}" if isinstance(current_price, (int, float)) else f"Current: {current_price}",
        f"Down from ATH: {pct_down:.2f}%" if isinstance(pct_down, (int, float)) else f"Down: {pct_down}",
        f"Days Since ATH: {ath.get('days_since', 'N/A')}",
    ]
    return "\n".join(lines)
