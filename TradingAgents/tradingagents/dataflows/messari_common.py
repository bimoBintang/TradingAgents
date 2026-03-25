"""Messari API common utilities — HTTP client, auth, rate limiting.

Base URL: https://data.messari.io/api
Auth: x-messari-api-key header
"""

import os
import time
import logging
import requests
from functools import lru_cache
from typing import Any, Dict, Optional

logger = logging.getLogger("dataflows.messari")

API_BASE_URL = "https://data.messari.io/api"

# Simple in-memory rate limiter (20 req/min for free tier)
_last_request_time: float = 0.0
_MIN_INTERVAL: float = 3.0  # seconds between requests


class MessariRateLimitError(Exception):
    """Raised when Messari API rate limit (HTTP 429) is hit."""
    pass


class MessariAPIError(Exception):
    """Raised for non-rate-limit Messari API errors."""
    pass


def get_api_key() -> str:
    """Retrieve the Messari API key from environment."""
    key = os.getenv("MESSARI_API_KEY", "")
    return key  # Messari allows keyless access with lower rate limits


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
    version: str = "v1",
) -> Dict[str, Any]:
    """Make an authenticated GET request to Messari API.

    Parameters
    ----------
    endpoint : str
        API path after version, e.g. ``"assets/bitcoin/metrics"``.
    params : dict, optional
        Query string parameters.
    version : str
        API version (``"v1"`` or ``"v2"``).

    Returns
    -------
    dict
        Parsed JSON response (the ``"data"`` key if present, else full body).

    Raises
    ------
    MessariRateLimitError
        On HTTP 429.
    MessariAPIError
        On any other non-200 response.
    """
    _throttle()

    url = f"{API_BASE_URL}/{version}/{endpoint}"
    headers = {}
    api_key = get_api_key()
    if api_key:
        headers["x-messari-api-key"] = api_key

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException as e:
        raise MessariAPIError(f"Messari network error: {e}")

    if resp.status_code == 429:
        raise MessariRateLimitError("Messari API rate limit exceeded")

    if resp.status_code != 200:
        raise MessariAPIError(
            f"Messari API error {resp.status_code}: {resp.text[:300]}"
        )

    body = resp.json()
    return body.get("data", body)


def ticker_to_slug(ticker: str) -> str:
    """Convert common ticker symbols to Messari slug format.

    Examples: BTC-USD → bitcoin, ETH-USD → ethereum, SOL → solana
    """
    KNOWN = {
        "BTC": "bitcoin", "BTC-USD": "bitcoin",
        "ETH": "ethereum", "ETH-USD": "ethereum",
        "SOL": "solana", "SOL-USD": "solana",
        "ADA": "cardano", "ADA-USD": "cardano",
        "DOT": "polkadot", "DOT-USD": "polkadot",
        "AVAX": "avalanche-2", "AVAX-USD": "avalanche-2",
        "MATIC": "polygon", "MATIC-USD": "polygon",
        "LINK": "chainlink", "LINK-USD": "chainlink",
        "UNI": "uniswap", "UNI-USD": "uniswap",
        "DOGE": "dogecoin", "DOGE-USD": "dogecoin",
        "XRP": "xrp", "XRP-USD": "xrp",
        "LTC": "litecoin", "LTC-USD": "litecoin",
        "ATOM": "cosmos", "ATOM-USD": "cosmos",
        "NEAR": "near-protocol", "NEAR-USD": "near-protocol",
        "APT": "aptos", "APT-USD": "aptos",
        "ARB": "arbitrum", "ARB-USD": "arbitrum",
        "OP": "optimism", "OP-USD": "optimism",
    }
    upper = ticker.upper().strip()
    if upper in KNOWN:
        return KNOWN[upper]
    # Fallback: lowercase and strip trailing -USD
    slug = upper.replace("-USD", "").replace("/", "-").lower()
    return slug
