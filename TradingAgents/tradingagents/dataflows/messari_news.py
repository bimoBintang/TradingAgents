"""Messari news — asset-specific and global crypto news."""

import logging
from typing import Optional

from .messari_common import make_request, ticker_to_slug, MessariAPIError

logger = logging.getLogger("dataflows.messari.news")


def get_news(ticker: str, *args, **kwargs) -> str:
    """Fetch news articles related to a specific asset.

    Compatible with the ``get_news`` vendor interface.
    Uses Messari v1 news endpoint with asset slug filter.
    """
    slug = ticker_to_slug(ticker)
    try:
        data = make_request("news", params={"assetSlugs": slug, "limit": 10}, version="v1")
    except MessariAPIError as e:
        return f"[Messari] News error for {ticker}: {e}"

    if not isinstance(data, list):
        data = data if isinstance(data, list) else []

    if not data:
        return f"[Messari] No news found for {ticker}"

    lines = [f"=== Messari News: {ticker} ({len(data)} articles) ==="]
    for article in data[:10]:
        title = article.get("title", "Untitled")
        published = article.get("published_at", "")[:10]
        url = article.get("url", "")
        author = article.get("author", {})
        author_name = author.get("name", "Unknown") if isinstance(author, dict) else str(author)
        lines.append(f"  [{published}] {title} — {author_name}")
        if url:
            lines.append(f"    {url}")

    return "\n".join(lines)


def get_global_news(*args, **kwargs) -> str:
    """Fetch latest global crypto news from Messari.

    Compatible with the ``get_global_news`` vendor interface.
    """
    try:
        data = make_request("news", params={"limit": 15}, version="v1")
    except MessariAPIError as e:
        return f"[Messari] Global news error: {e}"

    if not isinstance(data, list):
        data = data if isinstance(data, list) else []

    if not data:
        return "[Messari] No global news available"

    lines = [f"=== Messari Global News ({len(data)} articles) ==="]
    for article in data[:15]:
        title = article.get("title", "Untitled")
        published = article.get("published_at", "")[:10]
        tags = ", ".join(article.get("tags", [])[:3])
        lines.append(f"  [{published}] {title}")
        if tags:
            lines.append(f"    Tags: {tags}")

    return "\n".join(lines)
