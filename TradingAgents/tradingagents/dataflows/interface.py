import logging
from typing import Annotated

logger = logging.getLogger(__name__)

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .messari import (
    get_stock as get_messari_stock,
    get_fundamentals as get_messari_fundamentals,
    get_balance_sheet as get_messari_balance_sheet,
    get_cashflow as get_messari_cashflow,
    get_income_statement as get_messari_income_statement,
    get_insider_transactions as get_messari_insider_transactions,
    get_news as get_messari_news,
    get_global_news as get_messari_global_news,
)
from .messari_common import MessariRateLimitError
from .coingecko import (
    get_stock as get_coingecko_stock,
    get_fundamentals as get_coingecko_fundamentals,
    get_balance_sheet as get_coingecko_balance_sheet,
    get_cashflow as get_coingecko_cashflow,
    get_income_statement as get_coingecko_income_statement,
    get_insider_transactions as get_coingecko_insider_transactions,
    get_news as get_coingecko_news,
    get_global_news as get_coingecko_global_news,
)
from .coingecko_common import CoinGeckoRateLimitError
from .tradingview import (
    get_tradingview_indicators,
    TradingViewRateLimitError,
)
from . import mcp_client as _mcp_client
from .mcp_client import MCPVendorError, MCPVendorNotConfigured

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "messari",
    "coingecko",
    "tradingview",
    "mcp",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "messari": get_messari_stock,
        "coingecko": get_coingecko_stock,
        "mcp": _mcp_client.get_stock_data,
    },
    # technical_indicators
    "get_indicators": {
        "tradingview": get_tradingview_indicators,
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "mcp": _mcp_client.get_indicators,
    },
    # fundamental_data
    "get_fundamentals": {
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "messari": get_messari_fundamentals,
        "coingecko": get_coingecko_fundamentals,
        "mcp": _mcp_client.get_fundamentals,
    },
    "get_balance_sheet": {
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "messari": get_messari_balance_sheet,
        "coingecko": get_coingecko_balance_sheet,
        "mcp": _mcp_client.get_balance_sheet,
    },
    "get_cashflow": {
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "messari": get_messari_cashflow,
        "coingecko": get_coingecko_cashflow,
        "mcp": _mcp_client.get_cashflow,
    },
    "get_income_statement": {
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "messari": get_messari_income_statement,
        "coingecko": get_coingecko_income_statement,
        "mcp": _mcp_client.get_income_statement,
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "messari": get_messari_news,
        "coingecko": get_coingecko_news,
        "mcp": _mcp_client.get_news,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "messari": get_messari_global_news,
        "coingecko": get_coingecko_global_news,
        "mcp": _mcp_client.get_global_news,
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "messari": get_messari_insider_transactions,
        "coingecko": get_coingecko_insider_transactions,
        "mcp": _mcp_client.get_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

import inspect

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    requested_vendor = kwargs.pop("vendor", None)
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if requested_vendor:
        primary_vendors.insert(0, requested_vendor.strip())

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        # Filter kwargs to only pass parameters accepted by impl_func
        try:
            sig = inspect.signature(impl_func)
            has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if has_var_kwargs:
                call_kwargs = kwargs
            else:
                call_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
            return impl_func(*args, **call_kwargs)
        except (AlphaVantageRateLimitError, MessariRateLimitError, CoinGeckoRateLimitError, TradingViewRateLimitError):
            continue  # Rate limits trigger fallback
        except MCPVendorNotConfigured:
            continue  # mcp vendor not set up — same fallback treatment as a rate limit
        except MCPVendorError as e:
            logger.warning("MCP vendor call failed for '%s', falling back: %s", method, e)
            continue

    raise RuntimeError(f"No available vendor for '{method}'")