"""FastAPI application entry point.

Run with:
    uvicorn api.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import init_graph
from api.routers import system, portfolio, journal, analysis, config, market_data, admin, patterns, pending, tradingview
from api.routers import websocket as ws_router
from api.auth import get_current_user
from api.database import engine, SessionLocal
from api.models import Base
from api.limiter import limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB and TradingAgentsGraph."""
    logger.info("🚀 Initialising Turso SQLite Database…")
    Base.metadata.create_all(bind=engine)
    
    with SessionLocal() as db:
        pass # Migrated to Clerk Just-in-time identity sync

    logger.info("🚀 Initialising TradingAgents Graph…")
    init_graph()  # graceful — never raises

    yield
    logger.info("🛑 Shutting down API…")


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
app.include_router(ws_router.router)

# ── Metrics ───────────────────────────────────────────────────────────
from api.metrics import setup_metrics
setup_metrics(app)
