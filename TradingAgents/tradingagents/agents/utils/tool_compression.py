"""Generic tool-output compression — Settings > AI Language Models >
"Compress tool output (RTK)".

This app's tools (get_stock_data, get_news, get_indicators, financial
statements, ...) return the same class of large, repetitive, mostly
boilerplate text that git diff/grep/ls/tree/log output represents for a
coding agent — the same compression principle applies: shrink it before
it becomes input tokens in the next LLM call, without changing what the
tool is named or how an agent calls it.

Wraps every tool registered on a ToolNode in place (same object, same
name/description/args_schema — agents keep calling it exactly as before)
so its return string gets compressed post-hoc. No-op when disabled.
"""

import copy
import re
import logging
from typing import List

logger = logging.getLogger(__name__)

# Keep well within a reasonable per-tool-call budget. Applied per tool
# call, not per report — a single verbose get_news or get_balance_sheet
# result is what this targets, not the agent's cumulative context.
MAX_CHARS = 8000


def compress_text(text: str, max_chars: int = MAX_CHARS) -> str:
    """Best-effort compression for one tool's text output:
    - collapse runs of 3+ blank lines into one
    - collapse repeated inline whitespace
    - if still too long, keep the head and tail (the summary/most recent
      rows are usually there) and elide the noisy middle with a marker
      stating how much was cut, so the agent knows data was omitted
      rather than silently seeing a truncated tail.
    """
    if not isinstance(text, str) or len(text) <= max_chars:
        return text

    collapsed = re.sub(r"\n{3,}", "\n\n", text)
    collapsed = re.sub(r"[ \t]{2,}", " ", collapsed)
    if len(collapsed) <= max_chars:
        return collapsed

    half = max_chars // 2
    head, tail = collapsed[:half], collapsed[-half:]
    omitted = len(collapsed) - len(head) - len(tail)
    return f"{head}\n\n… [{omitted} chars omitted by tool-output compression — RTK] …\n\n{tail}"


def _wrap(func):
    def wrapped(*args, **kwargs):
        result = func(*args, **kwargs)
        return compress_text(result) if isinstance(result, str) else result
    return wrapped


def compress_tools(tools: List, enabled: bool) -> List:
    """Return tools with their string output compressed — via a shallow
    COPY of each tool, never by mutating the original in place.

    The tool objects passed in (get_stock_data, get_news, ...) are
    module-level singletons shared across every TradingAgentsGraph in
    this process — this is a multi-tenant SaaS app, so several different
    users' graphs can be alive at once, each with their OWN
    compress_tool_output setting. Mutating a shared tool's `.func`
    directly would leak one user's compression setting onto every other
    user's concurrent analysis using that same tool. `copy.copy()` gives
    each ToolNode its own tool instance instead, so this stays isolated
    per-request. Returns `tools` unchanged (same objects, no copies) when
    `enabled` is False, so this is a safe no-op to call unconditionally.
    """
    if not enabled:
        return tools
    result = []
    for t in tools:
        func = getattr(t, "func", None)
        if func is None or getattr(func, "_rtk_wrapped", False):
            result.append(t)
            continue
        t_copy = copy.copy(t)
        wrapped = _wrap(func)
        wrapped._rtk_wrapped = True
        t_copy.func = wrapped
        result.append(t_copy)
        # Async tools (`coroutine`) aren't wrapped — none of the current
        # dataflow tools are async; add an async version here if that changes.
    return result
