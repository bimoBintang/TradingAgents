"""Prometheus metrics for TradingAgents API.

Provides:
- Auto HTTP metrics via prometheus-fastapi-instrumentator
- Custom business metrics (users, tasks, WS connections, trades)
- setup_metrics() to attach to FastAPI app

All imports are graceful — app works without prometheus installed.
"""

import logging
from typing import Callable

logger = logging.getLogger("api.metrics")

try:
    from prometheus_client import Counter, Gauge, Info
    _prometheus_available = True
except ImportError:
    _prometheus_available = False
    logger.warning("prometheus_client not installed. Metrics disabled.")

    # No-op stubs
    class _NoOp:
        def __init__(self, *a, **kw): pass
        def labels(self, **kw): return self
        def inc(self, *a): pass
        def set(self, *a): pass
        def info(self, *a): pass

    Counter = Gauge = Info = _NoOp  # type: ignore

# ── Custom Business Metrics ───────────────────────────────────────────

APP_INFO = Info(
    "tradingagents",
    "TradingAgents application info",
)

ACTIVE_WS_CONNECTIONS = Gauge(
    "tradingagents_ws_connections_active",
    "Number of active WebSocket connections",
)

TASKS_CREATED = Counter(
    "tradingagents_tasks_created_total",
    "Total analysis tasks created",
    ["status"],
)

TRADES_EXECUTED = Counter(
    "tradingagents_trades_executed_total",
    "Total trades executed",
    ["side", "status"],
)

HTTP_REQUESTS = Counter(
    "tradingagents_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Gauge(
    "tradingagents_request_latency_seconds",
    "Latest request latency in seconds",
    ["method", "endpoint"],
)


def setup_metrics(app):
    """Attach Prometheus instrumentation to the FastAPI app.

    Exposes /metrics endpoint for Prometheus scraper.
    Falls back gracefully if instrumentator not installed.
    """
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        instrumentator = Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_round_latency_decimals=True,
            excluded_handlers=["/metrics", "/api/health"],
            inprogress_name="tradingagents_http_inprogress",
            inprogress_labels=True,
        )

        instrumentator.instrument(app).expose(app, endpoint="/metrics")

        APP_INFO.info({
            "version": "1.0.0",
            "framework": "fastapi",
        })

        logger.info("Prometheus metrics enabled at /metrics")

    except ImportError:
        logger.warning(
            "prometheus-fastapi-instrumentator not installed. "
            "Metrics endpoint disabled. Install with: "
            "pip install prometheus-fastapi-instrumentator"
        )


# ── Helper functions for recording business events ────────────────────

def record_task_created(status: str = "queued"):
    """Record a new analysis task creation."""
    TASKS_CREATED.labels(status=status).inc()


def record_trade(side: str, status: str):
    """Record a trade execution."""
    TRADES_EXECUTED.labels(side=side, status=status).inc()


def update_ws_connections(count: int):
    """Update the active WebSocket connection gauge."""
    ACTIVE_WS_CONNECTIONS.set(count)
