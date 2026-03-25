"""Advanced data tools for the new specialist agents.

Provides: options chain, on-chain metrics, funding rates,
macro indicators, and peer group data.

All tools include graceful degradation — on failure they return
structured JSON with `{"status": "degraded", ...}` instead of
raising exceptions that would crash the LangGraph pipeline.
"""

from langchain_core.tools import tool
from typing import Annotated
import json
import logging
import time
from functools import wraps

logger = logging.getLogger("tradingagents.tools.advanced")


# ── Graceful Degradation Wrapper ──────────────────────────────────────

def resilient_tool(max_retries: int = 2, timeout_seconds: int = 15):
    """Decorator that wraps tool functions with retry, timeout, and fallback.

    On failure after retries, returns a structured degraded response
    instead of raising, preventing cascade failures in the graph.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    start = time.monotonic()
                    result = func(*args, **kwargs)
                    elapsed = time.monotonic() - start

                    if elapsed > timeout_seconds:
                        logger.warning(
                            f"[{func.__name__}] Slow response: {elapsed:.1f}s"
                        )

                    return result

                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"[{func.__name__}] Attempt {attempt}/{max_retries} "
                        f"failed: {type(e).__name__}: {e}"
                    )
                    if attempt < max_retries:
                        time.sleep(0.5 * attempt)  # Backoff

            # All retries exhausted — return degraded response
            logger.error(
                f"[{func.__name__}] All {max_retries} retries exhausted. "
                f"Returning degraded response."
            )
            return json.dumps({
                "status": "degraded",
                "tool": func.__name__,
                "error": str(last_error),
                "message": (
                    f"Data source temporarily unavailable. "
                    f"The {func.__name__} tool failed after {max_retries} retries. "
                    f"Proceed with analysis using other available data."
                ),
            })
        return wrapper
    return decorator


# ── Tools ─────────────────────────────────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_options_chain(
    symbol: Annotated[str, "Ticker symbol, e.g. AAPL or BTC-USD"],
    date: Annotated[str, "Reference date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve options chain data including put/call ratio,
    implied volatility skew, and open interest for the nearest expiry.
    """
    import yfinance as yf

    tk = yf.Ticker(symbol)
    expirations = tk.options
    if not expirations:
        return json.dumps({
            "status": "no_data",
            "symbol": symbol,
            "message": f"No options data available for {symbol}. "
                       "This is normal for crypto and some small-cap equities.",
        })

    nearest = expirations[0]
    opt = tk.option_chain(nearest)

    calls_oi = int(opt.calls["openInterest"].sum()) if "openInterest" in opt.calls.columns else 0
    puts_oi = int(opt.puts["openInterest"].sum()) if "openInterest" in opt.puts.columns else 0
    pc_ratio = round(puts_oi / max(calls_oi, 1), 3)

    calls_iv = round(float(opt.calls["impliedVolatility"].mean()), 4) if "impliedVolatility" in opt.calls.columns else None
    puts_iv = round(float(opt.puts["impliedVolatility"].mean()), 4) if "impliedVolatility" in opt.puts.columns else None

    return json.dumps({
        "status": "ok",
        "symbol": symbol,
        "nearest_expiry": nearest,
        "total_call_oi": calls_oi,
        "total_put_oi": puts_oi,
        "put_call_ratio": pc_ratio,
        "avg_call_iv": calls_iv,
        "avg_put_iv": puts_iv,
        "iv_skew": round((puts_iv or 0) - (calls_iv or 0), 4),
        "num_expirations": len(expirations),
    }, indent=2)


@tool
@resilient_tool(max_retries=3, timeout_seconds=12)
def get_onchain_metrics(
    symbol: Annotated[str, "Crypto symbol, e.g. bitcoin, ethereum, BTC-USD"],
) -> str:
    """
    Retrieve on-chain and DeFi metrics from CoinGecko free API.
    Includes market cap, 24h volume, circulating supply, and price change.
    """
    import urllib.request

    coin_id = symbol.lower().replace("-usd", "").replace("-usdt", "")
    TICKER_MAP = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
        "doge": "dogecoin", "ada": "cardano", "xrp": "ripple",
        "bnb": "binancecoin", "avax": "avalanche-2", "dot": "polkadot",
        "matic": "matic-network", "link": "chainlink", "uni": "uniswap",
        "aave": "aave", "ltc": "litecoin", "atom": "cosmos",
        "near": "near", "arb": "arbitrum", "op": "optimism",
        "apt": "aptos", "sui": "sui", "pepe": "pepe",
        "shib": "shiba-inu", "fil": "filecoin", "inj": "injective-protocol",
    }
    coin_id = TICKER_MAP.get(coin_id, coin_id)

    url = (
        f"https://api.coingecko.com/api/v3/coins/{coin_id}"
        f"?localization=false&tickers=false&community_data=false&developer_data=false"
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "TradingAgents/1.0",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    market = data.get("market_data", {})
    return json.dumps({
        "status": "ok",
        "coin": coin_id,
        "current_price_usd": market.get("current_price", {}).get("usd"),
        "market_cap_usd": market.get("market_cap", {}).get("usd"),
        "total_volume_24h": market.get("total_volume", {}).get("usd"),
        "circulating_supply": market.get("circulating_supply"),
        "max_supply": market.get("max_supply"),
        "price_change_24h_pct": market.get("price_change_percentage_24h"),
        "price_change_7d_pct": market.get("price_change_percentage_7d"),
        "price_change_30d_pct": market.get("price_change_percentage_30d"),
        "ath_usd": market.get("ath", {}).get("usd"),
        "ath_change_pct": market.get("ath_change_percentage", {}).get("usd"),
        "sentiment_up_pct": data.get("sentiment_votes_up_percentage"),
        "sentiment_down_pct": data.get("sentiment_votes_down_percentage"),
    }, indent=2)


@tool
@resilient_tool(max_retries=2, timeout_seconds=10)
def get_funding_rates(
    symbol: Annotated[str, "Crypto symbol, e.g. BTC, ETH, BTC-USD"],
) -> str:
    """
    Retrieve current perpetual futures funding rates from Binance public API.
    Positive funding = longs pay shorts (bullish crowding).
    Negative funding = shorts pay longs (bearish crowding).
    """
    import urllib.request

    ticker = symbol.upper().replace("-USD", "").replace("-USDT", "").replace("USD", "")
    binance_symbol = f"{ticker}USDT"

    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={binance_symbol}&limit=10"
    req = urllib.request.Request(url, headers={"User-Agent": "TradingAgents/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    if not data:
        return json.dumps({
            "status": "no_data",
            "symbol": binance_symbol,
            "message": f"No funding rate data for {binance_symbol}",
        })

    rates = [{"time": r.get("fundingTime"), "rate": float(r.get("fundingRate", 0))} for r in data]
    latest = rates[-1]["rate"] if rates else 0
    avg = sum(r["rate"] for r in rates) / len(rates) if rates else 0

    sentiment = "neutral"
    if latest > 0.0005:
        sentiment = "bullish_crowding (longs dominant)"
    elif latest < -0.0005:
        sentiment = "bearish_crowding (shorts dominant)"

    return json.dumps({
        "status": "ok",
        "symbol": binance_symbol,
        "latest_funding_rate": round(latest, 6),
        "avg_funding_rate_10": round(avg, 6),
        "sentiment_signal": sentiment,
        "history": rates[-5:],
    }, indent=2)


@tool
@resilient_tool(max_retries=2, timeout_seconds=20)
def get_macro_indicators(
    date: Annotated[str, "Reference date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve macroeconomic indicators: DXY (Dollar Index), 10Y Treasury yield,
    VIX (fear index), Gold, and Oil prices using yfinance batch download.
    """
    import yfinance as yf
    from datetime import datetime, timedelta

    end = datetime.strptime(date, "%Y-%m-%d")
    start = end - timedelta(days=90)
    start_str = start.strftime("%Y-%m-%d")

    tickers_map = {
        "DX-Y.NYB": "DXY (Dollar Index)",
        "^TNX": "10Y Treasury Yield",
        "^VIX": "VIX (Fear Index)",
        "GC=F": "Gold (XAU)",
        "CL=F": "Crude Oil (WTI)",
        "^GSPC": "S&P 500",
    }

    # Batch download — single HTTP call instead of 6 sequential ones
    symbols = list(tickers_map.keys())
    raw = yf.download(symbols, start=start_str, end=date, progress=False, group_by="ticker")

    results = {}
    for sym, name in tickers_map.items():
        try:
            if len(symbols) == 1:
                close = raw["Close"]
            else:
                close = raw[sym]["Close"] if sym in raw.columns.get_level_values(0) else None

            if close is None or close.dropna().empty:
                results[name] = {"error": "No data"}
                continue

            close = close.dropna()
            latest = float(close.iloc[-1])
            prev_idx = -min(22, len(close))
            prev_30 = float(close.iloc[prev_idx])

            results[name] = {
                "latest": round(latest, 2),
                "30d_ago": round(prev_30, 2),
                "change_pct": round(((latest - prev_30) / prev_30) * 100, 2) if prev_30 else 0,
            }
        except Exception:
            results[name] = {"error": "fetch failed"}

    return json.dumps({"status": "ok", "date": date, "indicators": results}, indent=2)


@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_peer_data(
    symbol: Annotated[str, "Primary ticker symbol"],
    peers: Annotated[str, "Comma-separated peer tickers, e.g. QQQ,SPY,AAPL"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve price data for a peer group to calculate correlation,
    relative strength, and beta metrics.
    """
    import yfinance as yf

    peer_list = [p.strip() for p in peers.split(",") if p.strip()]
    all_tickers = [symbol] + peer_list

    data = yf.download(all_tickers, start=start_date, end=end_date, progress=False)
    if data.empty:
        return json.dumps({"status": "no_data", "error": "No data retrieved"})

    # Handle both single-ticker and multi-ticker DataFrame structures
    if "Close" in data.columns.get_level_values(0) if hasattr(data.columns, 'get_level_values') else "Close" in data.columns:
        close = data["Close"]
    else:
        close = data

    # Ensure we have a DataFrame, not a Series
    if hasattr(close, 'to_frame'):
        close = close.to_frame(symbol)

    returns = close.pct_change().dropna()

    results = {
        "status": "ok",
        "primary": symbol,
        "peers": peer_list,
        "period": f"{start_date} to {end_date}",
    }
    peer_metrics = {}

    for peer in peer_list:
        if peer in returns.columns and symbol in returns.columns:
            corr = float(returns[symbol].corr(returns[peer]))
            cov = float(returns[symbol].cov(returns[peer]))
            var = float(returns[peer].var())
            beta = round(cov / var, 3) if var > 0 else 0.0

            cum_sym = float((1 + returns[symbol]).prod() - 1)
            cum_peer = float((1 + returns[peer]).prod() - 1)

            peer_metrics[peer] = {
                "correlation": round(corr, 3),
                "beta": beta,
                "primary_return_pct": round(cum_sym * 100, 2),
                "peer_return_pct": round(cum_peer * 100, 2),
                "relative_strength": round((cum_sym - cum_peer) * 100, 2),
            }
        else:
            peer_metrics[peer] = {"error": "data not available"}

    results["metrics"] = peer_metrics
    return json.dumps(results, indent=2)
