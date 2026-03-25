"""SQLAlchemy database engine and session factory.

Supports multiple backends:
- PostgreSQL: DATABASE_URL=postgresql://user:pass@host/dbname
- SQLite:     DATABASE_URL=sqlite:///path/to/db.sqlite
- Turso:      DATABASE_URL=libsql://your-db.turso.io  (+ TURSO_AUTH_TOKEN)
"""

import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("api.database")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in .env")

# ── Normalise URL for driver compatibility ────────────────────────────

_raw_url = DATABASE_URL

# Turso / LibSQL: convert libsql:// → sqlite+libsql://
if DATABASE_URL.startswith("libsql://"):
    DATABASE_URL = DATABASE_URL.replace("libsql://", "sqlite+libsql://")
    turso_auth_token = os.getenv("TURSO_AUTH_TOKEN")
    if turso_auth_token and "?" not in DATABASE_URL:
        DATABASE_URL = f"{DATABASE_URL}/?authToken={turso_auth_token}"

# ── Engine options per backend ────────────────────────────────────────

connect_args = {}
engine_kwargs = {}

if "sqlite" in DATABASE_URL:
    # SQLite: disable same-thread check for FastAPI async
    connect_args = {"check_same_thread": False}
elif "postgresql" in DATABASE_URL:
    # PostgreSQL: enable connection health checks & pool recycling
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,  # recycle connections every 5 min
    }

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

logger.info("Database engine created: %s", engine.url.get_backend_name())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session and auto-closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
