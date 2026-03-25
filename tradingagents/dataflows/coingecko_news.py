"""CoinGecko news — trending coins and global market overview."""

import logging

from .coingecko_common import make_request, ticker_to_id, CoinGeckoAPIError

logger = logging.getLogger("dataflows.coingecko.news")


def get_news(ticker: str, *args, **kwargs) -> str:
    """Fetch trending/relevant info for a specific asset.

    CoinGecko doesn't have a dedicated news endpoint per asset,
    so we combine coin details with market sentiment as proxy.
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
        return f"[CoinGecko] News error for {ticker}: {e}"

    if not isinstance(data, dict):
        return f"[CoinGecko] No data for {ticker}"

    community = data.get("community_data", {})
    market = data.get("market_data", {})
    desc = data.get("description", {}).get("en", "")
    if len(desc) > 300:
        desc = desc[:300] + "..."

    lines = [
        f"=== CoinGecko Asset Intel: {data.get('name', ticker)} ===",
        f"Sentiment: {data.get('sentiment_votes_up_percentage', '?')}% Bullish / {data.get('sentiment_votes_down_percentage', '?')}% Bearish",
        f"Community Score: {data.get('community_score', 'N/A')}",
        f"Twitter Followers: {community.get('twitter_followers', 'N/A')}",
        f"Reddit Active Users (48h): {community.get('reddit_accounts_active_48h', 'N/A')}",
        f"Watchlist: {data.get('watchlist_portfolio_users', 'N/A')} users on CoinGecko",
    ]

    # Price changes as "news" signals
    price_changes = market.get("price_change_percentage_24h_in_currency", {})
    pct_24h = market.get("price_change_percentage_24h", 0)
    pct_7d = market.get("price_change_percentage_7d", 0)
    pct_30d = market.get("price_change_percentage_30d", 0)

    lines.append(f"Price Changes: 24h={pct_24h:.1f}%, 7d={pct_7d:.1f}%, 30d={pct_30d:.1f}%")

    if desc:
        lines.append(f"Summary: {desc}")

    return "\n".join(lines)


def get_global_news(*args, **kwargs) -> str:
    """Fetch trending coins + global market overview.

    Combines /search/trending and /global endpoints.
    """
    lines = ["=== CoinGecko Global Market Overview ==="]

    # 1. Global market data
    try:
        gdata = make_request("global")
        if isinstance(gdata, dict):
            d = gdata.get("data", gdata)
            lines.extend([
                f"Active Cryptocurrencies: {d.get('active_cryptocurrencies', 'N/A')}",
                f"Total Market Cap: ${d.get('total_market_cap', {}).get('usd', 0):,.0f}",
                f"24h Volume: ${d.get('total_volume', {}).get('usd', 0):,.0f}",
                f"BTC Dominance: {d.get('market_cap_percentage', {}).get('btc', 0):.1f}%",
                f"ETH Dominance: {d.get('market_cap_percentage', {}).get('eth', 0):.1f}%",
                f"Market Cap Change 24h: {d.get('market_cap_change_percentage_24h_usd', 0):.2f}%",
            ])
    except CoinGeckoAPIError as e:
        lines.append(f"Global data error: {e}")

    # 2. Trending coins
    try:
        trending = make_request("search/trending")
        coins = trending.get("coins", []) if isinstance(trending, dict) else []
        if coins:
            lines.append("\nTrending Coins (Top 7):")
            for item in coins[:7]:
                coin = item.get("item", {})
                name = coin.get("name", "?")
                symbol = coin.get("symbol", "?")
                rank = coin.get("market_cap_rank", "?")
                score = coin.get("score", "?")
                lines.append(f"  #{rank} {name} ({symbol}) — trend score: {score}")
    except CoinGeckoAPIError as e:
        lines.append(f"Trending error: {e}")

    return "\n".join(lines)
