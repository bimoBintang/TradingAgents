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
    # SQLite: disable same-thread check for FastAPI async.
    #
    # `timeout` is the busy timeout, and it matters here more than it looks.
    # This process writes to one SQLite file from several places at once:
    # request handlers, the background analysis thread (api/tasks.py), the
    # balance-sync scheduler job, and the benchmark resolver. SQLite's
    # default busy timeout is 0 — a writer that finds the database locked
    # fails INSTANTLY with "database is locked" rather than waiting.
    #
    # For a trading system that is a correctness problem, not a nuisance:
    # a failed write while recording a fill leaves the order live at the
    # exchange with no local record of it, which is exactly the drift that
    # reconciliation then has to guess about. 30s of waiting is cheap
    # compared to losing a trade record.
    connect_args = {"check_same_thread": False, "timeout": 30.0}
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

if "sqlite" in DATABASE_URL:
    # WAL lets readers proceed while a write is in flight. In the default
    # rollback-journal mode a single writer blocks every reader, so one
    # slow write (a fill being recorded, a balance sync) stalls unrelated
    # dashboard requests and makes lock contention far more likely.
    #
    # Applied per connection rather than once, because SQLAlchemy's pool
    # opens new connections over the process's lifetime and a PRAGMA only
    # affects the connection it runs on. journal_mode=WAL persists in the
    # database file itself; busy_timeout and synchronous do not.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            # NORMAL is the standard durability/throughput trade-off under
            # WAL: safe against process crashes, and only at risk of losing
            # the most recent commits in an OS-level crash or power loss.
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

logger.info("Database engine created: %s", engine.url.get_backend_name())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session and auto-closes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
