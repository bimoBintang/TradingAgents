"""Polymarket prediction market tools for the LangGraph pipeline.

2 @tool functions:
  - get_prediction_markets: Search active events via Gamma API (public, no auth)
  - get_market_price: Get midpoint price for a specific market via CLOB API

Both APIs are free and require no authentication for read-only access.
"""

from langchain_core.tools import tool
from typing import Annotated
import json
import logging

import httpx

from tradingagents.agents.utils.advanced_tools import resilient_tool

logger = logging.getLogger("tradingagents.tools.polymarket")

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
TIMEOUT = 10


# ── Tool 1: Search Prediction Markets ────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=15)
def get_prediction_markets(
    query: Annotated[str, "Search query, e.g. 'bitcoin', 'fed rate', 'nvidia', 'SEC'"],
    limit: Annotated[int, "Max number of events to return"] = 10,
) -> str:
    """Search active Polymarket prediction markets for events matching a query.

    Uses the Gamma API (public, no auth required).
    Returns event titles, market questions, YES/NO probabilities, and volume.
    """
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # Search active (not closed) events
            resp = client.get(
                f"{GAMMA_BASE}/events",
                params={
                    "closed": "false",
                    "limit": min(limit, 20),
                    "order": "volume24hr",
                    "ascending": "false",
                    "title": query,
                },
            )
            resp.raise_for_status()
            events = resp.json()

        if not events:
            return json.dumps({
                "status": "no_results",
                "query": query,
                "message": f"No active Polymarket events found for '{query}'",
            })

        results = []
        for event in events[:limit]:
            # Extract tags as simple label list
            raw_tags = event.get("tags", []) or []
            tag_labels = [t.get("label", "") for t in raw_tags if t.get("label")]

            event_data = {
                "title": event.get("title", ""),
                "slug": event.get("slug", ""),
                "description": (event.get("description", "") or "")[:1000],
                "image": event.get("image", "") or "",
                "icon": event.get("icon", "") or "",
                "tags": tag_labels,
                "volume": float(event.get("volume", 0) or 0),
                "liquidity": float(event.get("liquidity", 0) or 0),
                "start_date": event.get("startDate", ""),
                "end_date": event.get("endDate", ""),
                "markets": [],
            }

            for market in (event.get("markets", []) or [])[:5]:
                outcome_prices = market.get("outcomePrices", "[]")
                if isinstance(outcome_prices, str):
                    try:
                        prices = json.loads(outcome_prices)
                    except (json.JSONDecodeError, TypeError):
                        prices = []
                else:
                    prices = outcome_prices

                yes_price = float(prices[0]) if len(prices) > 0 else 0.0
                no_price = float(prices[1]) if len(prices) > 1 else 0.0

                event_data["markets"].append({
                    "question": market.get("question", ""),
                    "yes_price": round(yes_price, 4),
                    "no_price": round(no_price, 4),
                    "yes_pct": round(yes_price * 100, 1),
                    "volume": float(market.get("volume", 0) or 0),
                    "condition_id": market.get("conditionId", ""),
                })

            results.append(event_data)

        return json.dumps({
            "status": "ok",
            "query": query,
            "count": len(results),
            "events": results,
        })

    except httpx.HTTPStatusError as e:
        logger.warning(f"Polymarket Gamma API error: {e}")
        return json.dumps({
            "status": "api_error",
            "query": query,
            "message": f"Gamma API returned {e.response.status_code}",
        })
    except httpx.RequestError as e:
        logger.warning(f"Polymarket network error: {e}")
        return json.dumps({
            "status": "network_error",
            "query": query,
            "message": str(e),
        })


# ── Tool 2: Get Market Midpoint Price ─────────────────────────────────

@tool
@resilient_tool(max_retries=2, timeout_seconds=10)
def get_market_price(
    condition_id: Annotated[str, "Polymarket condition ID for the market"],
) -> str:
    """Get the current YES/NO midpoint price for a specific Polymarket market.

    Uses the CLOB API (public, no auth required for read-only).
    """
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                f"{CLOB_BASE}/midpoint",
                params={"token_id": condition_id},
            )
            resp.raise_for_status()
            data = resp.json()

        mid = float(data.get("mid", 0))

        return json.dumps({
            "status": "ok",
            "condition_id": condition_id,
            "yes_price": round(mid, 4),
            "no_price": round(1 - mid, 4),
            "yes_pct": round(mid * 100, 1),
        })

    except httpx.HTTPStatusError as e:
        logger.warning(f"Polymarket CLOB API error: {e}")
        return json.dumps({
            "status": "api_error",
            "condition_id": condition_id,
            "message": f"CLOB API returned {e.response.status_code}",
        })
    except httpx.RequestError as e:
        logger.warning(f"Polymarket network error: {e}")
        return json.dumps({
            "status": "network_error",
            "condition_id": condition_id,
            "message": str(e),
        })
