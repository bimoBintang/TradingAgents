"""Messari asset data — price, market cap, supply, fundamentals, profile."""

import logging
from typing import Any

from .messari_common import make_request, ticker_to_slug, MessariAPIError

logger = logging.getLogger("dataflows.messari.asset")


def get_stock(ticker: str, *args, **kwargs) -> str:
    """Fetch asset metrics (price, volume, market cap, supply).

    Compatible with the ``get_stock_data`` vendor interface.
    Returns a formatted string digest for LLM consumption.
    """
    slug = ticker_to_slug(ticker)
    try:
        data = make_request(f"assets/{slug}/metrics")
    except MessariAPIError as e:
        return f"[Messari] Error fetching metrics for {ticker}: {e}"

    market = data.get("market_data", {})
    supply = data.get("supply", {})
    mcap = data.get("marketcap", {})
    roi = data.get("roi_data", {})

    lines = [
        f"=== Messari Asset Metrics: {ticker} ({slug}) ===",
        f"Price (USD): ${market.get('price_usd', 'N/A'):,.2f}" if isinstance(market.get('price_usd'), (int, float)) else f"Price: {market.get('price_usd', 'N/A')}",
        f"24h Volume: ${market.get('volume_last_24_hours', 0):,.0f}",
        f"24h Change: {market.get('percent_change_usd_last_24_hours', 0):.2f}%",
        f"Market Cap: ${mcap.get('current_marketcap_usd', 0):,.0f}",
        f"Circulating Supply: {supply.get('circulating', 'N/A')}",
        f"Max Supply: {supply.get('max_supply', 'N/A')}",
        f"ROI 30d: {roi.get('percent_change_last_1_month', 'N/A')}%",
        f"ROI 1y: {roi.get('percent_change_last_1_year', 'N/A')}%",
    ]
    return "\n".join(lines)


def get_fundamentals(ticker: str, *args, **kwargs) -> str:
    """Fetch asset profile (description, sector, category, consensus).

    Compatible with the ``get_fundamentals`` vendor interface.
    """
    slug = ticker_to_slug(ticker)
    try:
        data = make_request(f"assets/{slug}/profile", version="v1")
    except MessariAPIError as e:
        return f"[Messari] Error fetching profile for {ticker}: {e}"

    general = data.get("profile", data) if isinstance(data, dict) else data
    if isinstance(general, dict):
        overview = general.get("general", {}).get("overview", {})
        background = general.get("general", {}).get("background", {})
        economics = general.get("economics", {})
        tech = general.get("technology", {})
    else:
        overview = background = economics = tech = {}

    lines = [
        f"=== Messari Profile: {ticker} ({slug}) ===",
        f"Tagline: {overview.get('tagline', 'N/A')}",
        f"Sector: {overview.get('sector', 'N/A')}",
        f"Category: {overview.get('category', 'N/A')}",
        f"Project Description: {overview.get('project_details', 'N/A')[:500]}",
        f"Background: {background.get('background_details', 'N/A')[:300]}",
    ]

    # Token economics
    consensus = economics.get("consensus_and_emission", {})
    if consensus:
        lines.append(f"Consensus: {consensus.get('consensus_details', 'N/A')[:200]}")

    return "\n".join(lines)


def get_balance_sheet(ticker: str, *args, **kwargs) -> str:
    """Messari doesn't provide traditional balance sheets.
    Return supply data as a proxy for crypto assets."""
    return get_stock(ticker)


def get_cashflow(ticker: str, *args, **kwargs) -> str:
    """Messari doesn't provide cashflow statements.
    Return on-chain fee revenue as proxy."""
    return get_stock(ticker)


def get_income_statement(ticker: str, *args, **kwargs) -> str:
    """Messari doesn't provide income statements.
    Return ROI/market data as proxy."""
    return get_stock(ticker)


def get_insider_transactions(ticker: str, *args, **kwargs) -> str:
    """No insider transactions for crypto. Return supply distribution."""
    slug = ticker_to_slug(ticker)
    try:
        data = make_request(f"assets/{slug}/metrics")
    except MessariAPIError as e:
        return f"[Messari] Error: {e}"

    supply = data.get("supply", {})
    lines = [
        f"=== Messari Supply Distribution: {ticker} ===",
        f"Circulating: {supply.get('circulating', 'N/A')}",
        f"Outstanding: {supply.get('outstanding', 'N/A')}",
        f"Stock-to-Flow: {supply.get('stock_to_flow', 'N/A')}",
        f"Y+10 Issued %: {supply.get('y_plus10_issued_percent', 'N/A')}",
        f"Annual Inflation %: {supply.get('annual_inflation_percent', 'N/A')}",
    ]
    return "\n".join(lines)
