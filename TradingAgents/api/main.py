"""FastAPI application entry point.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import init_graph
from api.routers import system, portfolio, journal, analysis, config, market_data, admin, patterns, pending, tradingview, chart_control
from api.routers import websocket as ws_router
from api.auth import get_current_user
from api.database import engine, SessionLocal
from api.models import Base
from api.limiter import limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from tradingagents.default_config import DEFAULT_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

_balance_sync_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB and TradingAgentsGraph."""
    global _balance_sync_scheduler

    logger.info("🚀 Initialising Turso SQLite Database…")
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        pass # Migrated to Clerk Just-in-time identity sync

    logger.info("🚀 Initialising TradingAgents Graph…")
    init_graph()  # graceful — never raises

    # ── Periodic real-broker balance sync (see api/services/balance_sync.py) ──
    # Keeps PortfolioState.cash_balance/total_equity/max_drawdown_pct in sync
    # with each live user's actual exchange balance — previously this only
    # ever happened once, at TradingAgentsGraph construction.
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from api.services.balance_sync import sync_all_live_users

        interval = int(os.getenv(
            "BALANCE_SYNC_INTERVAL_SECONDS",
            DEFAULT_CONFIG["execution"]["balance_sync_interval_seconds"],
        ))

        async def _run_balance_sync():
            # Must be an actual coroutine function (not a lambda wrapping
            # one) — AsyncIOScheduler only awaits jobs it detects via
            # asyncio.iscoroutinefunction(). A lambda returning a coroutine
            # gets called but never awaited: the coroutine object is
            # created and silently garbage-collected, so sync_all_live_users
            # never actually runs (confirmed via a
            # "coroutine was never awaited" RuntimeWarning during testing).
            await run_in_threadpool(sync_all_live_users)

        async def _run_benchmark_resolve():
            # Marks forward agent-vs-baseline decisions to market once their
            # horizon elapses (api/services/forward_benchmark.py). Hourly is
            # plenty — the default horizon is measured in days — and it must
            # never raise into the scheduler.
            def _resolve():
                from api.services.forward_benchmark import resolve_due
                with SessionLocal() as db:
                    try:
                        resolve_due(db)
                    except Exception as e:
                        logger.error("Benchmark resolve failed: %s", e)

            await run_in_threadpool(_resolve)

        _balance_sync_scheduler = AsyncIOScheduler()
        _balance_sync_scheduler.add_job(
            _run_balance_sync,
            "interval",
            seconds=interval,
            id="balance_sync",
            max_instances=1,  # never overlap a slow cycle with the next tick
            coalesce=True,
        )
        _balance_sync_scheduler.add_job(
            _run_benchmark_resolve,
            "interval",
            hours=1,
            id="benchmark_resolve",
            max_instances=1,
            coalesce=True,
        )
        _balance_sync_scheduler.start()
        logger.info(
            "🔄 Balance sync scheduler started (every %ds) + benchmark resolver (hourly)",
            interval,
        )
    except Exception as e:
        logger.error("Failed to start balance sync scheduler: %s. Live balances will not auto-refresh.", e)

    yield
    logger.info("🛑 Shutting down API…")
    if _balance_sync_scheduler is not None:
        _balance_sync_scheduler.shutdown(wait=False)


app = FastAPI(
    title="TradingAgents API",
    description="REST API for the Multi-Agent LLM Trading Framework",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Rate Limiting ─────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — allow the React dashboard ──────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server
        "http://localhost:3000",   # Alt dev server
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register Routers ──────────────────────────────────────────────────
app.include_router(system.router)
app.include_router(portfolio.router)
app.include_router(journal.router)
app.include_router(analysis.router)
app.include_router(config.router)
app.include_router(market_data.router)
app.include_router(patterns.router)
app.include_router(admin.router)
app.include_router(pending.router)
app.include_router(tradingview.router)
app.include_router(chart_control.router)
app.include_router(ws_router.router)

# ── Metrics ───────────────────────────────────────────────────────────
from api.metrics import setup_metrics
setup_metrics(app)
