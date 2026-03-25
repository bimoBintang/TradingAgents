"""CoinGecko API common utilities — HTTP client, rate limiting, id mapping.

Base URL: https://api.coingecko.com/api/v3
Auth: Optional x-cg-demo-api-key header (free tier works without key)
Rate limit: 30 calls/min (free), throttled to 2s between requests.
"""

import os
import time
import logging
import requests
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dataflows.coingecko")

API_BASE_URL = "https://api.coingecko.com/api/v3"

# Simple in-memory rate limiter
_last_request_time: float = 0.0
_MIN_INTERVAL: float = 2.0  # 30 calls/min ≈ 2s between requests


class CoinGeckoRateLimitError(Exception):
    """Raised when CoinGecko API rate limit (HTTP 429) is hit."""
    pass


class CoinGeckoAPIError(Exception):
    """Raised for non-rate-limit CoinGecko API errors."""
    pass


def get_api_key() -> str:
    """Retrieve optional CoinGecko Demo API key from environment."""
    return os.getenv("COINGECKO_API_KEY", "")


def _throttle():
    """Enforce minimum interval between requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.time()


def make_request(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Make a GET request to CoinGecko API v3.

    Returns parsed JSON (list or dict depending on endpoint).

    Raises
    ------
    CoinGeckoRateLimitError  on HTTP 429
    CoinGeckoAPIError        on any other non-200 response
    """
    _throttle()

    url = f"{API_BASE_URL}/{endpoint}"
    headers = {}
    api_key = get_api_key()
    if api_key:
        headers["x-cg-demo-api-key"] = api_key

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException as e:
        raise CoinGeckoAPIError(f"CoinGecko network error: {e}")

    if resp.status_code == 429:
        raise CoinGeckoRateLimitError("CoinGecko rate limit exceeded (429)")

    if resp.status_code != 200:
        raise CoinGeckoAPIError(
            f"CoinGecko API error {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()


# ── Ticker → CoinGecko ID mapper ─────────────────────────────────────

_KNOWN_IDS: Dict[str, str] = {
    "BTC": "bitcoin", "BTC-USD": "bitcoin",
    "ETH": "ethereum", "ETH-USD": "ethereum",
    "SOL": "solana", "SOL-USD": "solana",
    "ADA": "cardano", "ADA-USD": "cardano",
    "DOT": "polkadot", "DOT-USD": "polkadot",
    "AVAX": "avalanche-2", "AVAX-USD": "avalanche-2",
    "MATIC": "matic-network", "MATIC-USD": "matic-network",
    "LINK": "chainlink", "LINK-USD": "chainlink",
    "UNI": "uniswap", "UNI-USD": "uniswap",
    "DOGE": "dogecoin", "DOGE-USD": "dogecoin",
    "XRP": "ripple", "XRP-USD": "ripple",
    "LTC": "litecoin", "LTC-USD": "litecoin",
    "ATOM": "cosmos", "ATOM-USD": "cosmos",
    "NEAR": "near", "NEAR-USD": "near",
    "APT": "aptos", "APT-USD": "aptos",
    "ARB": "arbitrum", "ARB-USD": "arbitrum",
    "OP": "optimism", "OP-USD": "optimism",
    "BNB": "binancecoin", "BNB-USD": "binancecoin",
    "TRX": "tron", "TRX-USD": "tron",
    "SHIB": "shiba-inu", "SHIB-USD": "shiba-inu",
    "SUI": "sui", "SUI-USD": "sui",
}


def ticker_to_id(ticker: str) -> str:
    """Convert common ticker to CoinGecko coin id.

    Examples: BTC-USD → bitcoin, ETH → ethereum
    """
    upper = ticker.upper().strip()
    if upper in _KNOWN_IDS:
        return _KNOWN_IDS[upper]
    # Fallback: lowercase, strip -USD
    return upper.replace("-USD", "").replace("/", "-").lower()
