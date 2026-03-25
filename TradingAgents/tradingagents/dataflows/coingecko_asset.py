"""CoinGecko asset data — price, market cap, supply, ATH, and fundamentals."""

import logging
from typing import Any

from .coingecko_common import make_request, ticker_to_id, CoinGeckoAPIError

logger = logging.getLogger("dataflows.coingecko.asset")


def _fmt(val: Any, prefix: str = "$", suffix: str = "") -> str:
    """Format a numeric value or return 'N/A'."""
    if val is None:
        return "N/A"
    if isinstance(val, (int, float)):
        if abs(val) >= 1_000_000_000:
            return f"{prefix}{val / 1e9:,.2f}B{suffix}"
        if abs(val) >= 1_000_000:
            return f"{prefix}{val / 1e6:,.2f}M{suffix}"
        return f"{prefix}{val:,.2f}{suffix}"
    return str(val)


def get_stock(ticker: str, *args, **kwargs) -> str:
    """Fetch market data for a crypto asset.

    Compatible with the ``get_stock_data`` vendor interface.
    Uses /coins/markets endpoint for rich market data.
    """
    coin_id = ticker_to_id(ticker)
    try:
        data = make_request("coins/markets", params={
            "vs_currency": "usd",
            "ids": coin_id,
            "order": "market_cap_desc",
            "sparkline": "false",
        })
    except CoinGeckoAPIError as e:
        return f"[CoinGecko] Error fetching market data for {ticker}: {e}"

    if not data or not isinstance(data, list) or len(data) == 0:
        return f"[CoinGecko] No market data found for {ticker} (id={coin_id})"

    c = data[0]
    lines = [
        f"=== CoinGecko Market Data: {c.get('name', ticker)} ({c.get('symbol', '').upper()}) ===",
        f"Price (USD): {_fmt(c.get('current_price'))}",
        f"24h High: {_fmt(c.get('high_24h'))}",
        f"24h Low: {_fmt(c.get('low_24h'))}",
        f"24h Change: {_fmt(c.get('price_change_percentage_24h'), prefix='', suffix='%')}",
        f"Market Cap: {_fmt(c.get('market_cap'))}",
        f"Market Cap Rank: #{c.get('market_cap_rank', 'N/A')}",
        f"24h Volume: {_fmt(c.get('total_volume'))}",
        f"Circulating Supply: {_fmt(c.get('circulating_supply'), prefix='')}",
        f"Total Supply: {_fmt(c.get('total_supply'), prefix='')}",
        f"Max Supply: {_fmt(c.get('max_supply'), prefix='')}",
        f"ATH: {_fmt(c.get('ath'))} ({c.get('ath_date', 'N/A')[:10]})",
        f"ATH Drop: {_fmt(c.get('ath_change_percentage'), prefix='', suffix='%')}",
        f"ATL: {_fmt(c.get('atl'))} ({c.get('atl_date', 'N/A')[:10]})",
        f"Last Updated: {c.get('last_updated', 'N/A')}",
    ]
    return "\n".join(lines)


def get_fundamentals(ticker: str, *args, **kwargs) -> str:
    """Fetch detailed asset profile/fundamentals.

    Uses /coins/{id} for description, categories, genesis, links.
    """
    coin_id = ticker_to_id(ticker)
    try:
        data = make_request(f"coins/{coin_id}", params={
            "localization": "false",
            "tickers": "false",
            "community_data": "true",
            "developer_data": "false",
            "sparkline": "false",
        })
    except CoinGeckoAPIError as e:
        return f"[CoinGecko] Error fetching fundamentals for {ticker}: {e}"

    if not isinstance(data, dict):
        return f"[CoinGecko] Unexpected response for {ticker}"

    desc = data.get("description", {}).get("en", "N/A")
    if len(desc) > 500:
        desc = desc[:500] + "..."

    categories = ", ".join(data.get("categories", [])[:5]) or "N/A"
    links = data.get("links", {})
    homepage = links.get("homepage", [""])[0] if links.get("homepage") else "N/A"
    community = data.get("community_data", {})

    lines = [
        f"=== CoinGecko Profile: {data.get('name', ticker)} ({data.get('symbol', '').upper()}) ===",
        f"Categories: {categories}",
        f"Hashing Algorithm: {data.get('hashing_algorithm', 'N/A')}",
        f"Genesis Date: {data.get('genesis_date', 'N/A')}",
        f"Homepage: {homepage}",
        f"Description: {desc}",
        f"Twitter Followers: {_fmt(community.get('twitter_followers'), prefix='')}",
        f"Reddit Subscribers: {_fmt(community.get('reddit_subscribers'), prefix='')}",
        f"Sentiment Up: {data.get('sentiment_votes_up_percentage', 'N/A')}%",
        f"Sentiment Down: {data.get('sentiment_votes_down_percentage', 'N/A')}%",
    ]
    return "\n".join(lines)


def get_balance_sheet(ticker: str, *args, **kwargs) -> str:
    """No balance sheet for crypto. Return supply data as proxy."""
    return get_stock(ticker)


def get_cashflow(ticker: str, *args, **kwargs) -> str:
    """No cashflow for crypto. Return market data as proxy."""
    return get_stock(ticker)


def get_income_statement(ticker: str, *args, **kwargs) -> str:
    """No income statement for crypto. Return market data as proxy."""
    return get_stock(ticker)


def get_insider_transactions(ticker: str, *args, **kwargs) -> str:
    """No insider transactions for crypto. Return community sentiment."""
    return get_fundamentals(ticker)
