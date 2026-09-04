"""SQLite database layer for TradingAgents persistent storage.

Zero external dependencies — uses Python built-in sqlite3.
Thread-safe with WAL journal mode for Phase 6 scheduler compatibility.

Tables:
- trades: completed and rejected trades (idempotency_key as PK)
- decisions: raw LLM decisions with risk verdicts
- reflections: agent reflection narratives
- agent_memories: BM25 (situation, advice) pairs — SEPARATE columns
- portfolio_snapshots: periodic equity snapshots
- schema_version: migration tracking
"""

import logging
import os
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for TradingAgents persistent storage.

    Thread-safe with WAL journal mode. Auto-creates tables on first use.

    Usage:
        db = Database("~/.tradingagents/trading.db")
        db.insert_trade({...})
        trades = db.query_trades(ticker="NVDA")
    """

    CURRENT_SCHEMA_VERSION = 3

    def __init__(self, db_path: str = "~/.tradingagents/trading.db"):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file. Supports ~ expansion.
        """
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._migrate()
        logger.info("Connected to %s", self.db_path)

    def close(self):
        """Close the database connection."""
        with self._lock:
            self._conn.close()

    # ── Migration System ──────────────────────────────────────────────

    def _migrate(self):
        """Auto-create or upgrade database schema."""
        with self._lock:
            cur = self._conn.cursor()

            # Check if schema_version table exists
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            has_version_table = cur.fetchone() is not None

            current_version = 0
            if has_version_table:
                cur.execute("SELECT MAX(version) FROM schema_version")
                row = cur.fetchone()
                current_version = row[0] if row and row[0] else 0

            if current_version < 1:
                self._apply_v1(cur)
            if current_version < 2:
                self._apply_v2(cur)
            if current_version < 3:
                self._apply_v3(cur)

            self._conn.commit()

    def _apply_v1(self, cur: sqlite3.Cursor):
        """Schema version 1: initial tables."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,
                requested_qty REAL,
                filled_qty REAL,
                remaining_qty REAL,
                fill_price REAL,
                average_fill_price REAL,
                fill_time TEXT,
                realized_pnl REAL,
                status TEXT NOT NULL,
                broker TEXT,
                rejection_code TEXT,
                rejection_reason TEXT,
                risk_score REAL,
                confidence_score REAL,
                session_id TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT,
                ticker TEXT,
                action TEXT,
                confidence_score REAL,
                risk_score REAL,
                raw_llm_output TEXT,
                parsed_decision_json TEXT,
                risk_verdict_json TEXT,
                agent_reports_json TEXT,
                session_id TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT,
                ticker TEXT,
                session_id TEXT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                ticker TEXT,
                situation TEXT NOT NULL,
                advice TEXT NOT NULL,
                session_id TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cash REAL,
                total_equity REAL,
                open_positions_json TEXT,
                unrealized_pnl REAL,
                realized_pnl REAL,
                drawdown_pct REAL,
                session_id TEXT
            )
        """)

        # Create indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_session ON decisions(session_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reflections_agent ON reflections(agent_name, ticker)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_agent ON agent_memories(agent_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_session ON portfolio_snapshots(session_id)")

        cur.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (1, datetime.utcnow().isoformat()),
        )

    def _apply_v2(self, cur: sqlite3.Cursor):
        """Schema version 2: entry price cache for broker persistence."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entry_price_cache (
                symbol TEXT PRIMARY KEY,
                avg_price REAL NOT NULL,
                quantity REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cur.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (2, datetime.utcnow().isoformat()),
        )

    def _apply_v3(self, cur: sqlite3.Cursor):
        """Schema version 3: durable risk-control state.

        RiskController previously held the kill switch, the consecutive-loss
        counter and the rolling PnL window purely in memory. In the SaaS
        deployment a fresh TradingAgentsGraph — and therefore a fresh
        RiskController — is constructed for EVERY analysis run, so all of
        that reset to zero before each new decision: a tripped kill switch
        never blocked the next trade, and the drawdown that should have
        tripped it was recomputed from an empty history every time.

        `account_id` scoping is mandatory, not cosmetic: this database file
        is shared by every user (storage.db_path is a single global path),
        so an unkeyed row would give the whole platform one shared kill
        switch — one user's loss limit halting everyone, or worse, one
        user's fresh state clearing another's halt.
        """
        cur.execute("""
            CREATE TABLE IF NOT EXISTS risk_state (
                account_id TEXT PRIMARY KEY,
                kill_switch INTEGER NOT NULL DEFAULT 0,
                kill_switch_reason TEXT DEFAULT '',
                kill_switch_activated_date TEXT,
                consecutive_losses INTEGER NOT NULL DEFAULT 0,
                last_loss_time TEXT,
                pnl_window_json TEXT DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
        """)

        cur.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (3, datetime.utcnow().isoformat()),
        )

    # ── Risk State ────────────────────────────────────────────────────

    def load_risk_state(self, account_id: str) -> Optional[dict]:
        """Load persisted risk state for an account, or None if absent."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM risk_state WHERE account_id = ?", (account_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def save_risk_state(
        self,
        account_id: str,
        kill_switch: bool,
        kill_switch_reason: str,
        kill_switch_activated_date: Optional[str],
        consecutive_losses: int,
        last_loss_time: Optional[str],
        pnl_window_json: str,
    ) -> None:
        """Persist risk state for an account (upsert)."""
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO risk_state (
                    account_id, kill_switch, kill_switch_reason,
                    kill_switch_activated_date, consecutive_losses,
                    last_loss_time, pnl_window_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    1 if kill_switch else 0,
                    kill_switch_reason or "",
                    kill_switch_activated_date,
                    consecutive_losses,
                    last_loss_time,
                    pnl_window_json,
                    datetime.utcnow().isoformat(),
                ),
            )
            self._conn.commit()

    # ── Trades ────────────────────────────────────────────────────────

    def insert_trade(self, trade_data: dict) -> None:
        """Insert a new trade record.

        Args:
            trade_data: Dict with keys matching trades table columns.
                       Must include 'id', 'ticker', 'action', 'status', 'created_at'.
        """
        with self._lock:
            cols = ", ".join(trade_data.keys())
            placeholders = ", ".join(["?"] * len(trade_data))
            self._conn.execute(
                f"INSERT OR REPLACE INTO trades ({cols}) VALUES ({placeholders})",
                tuple(trade_data.values()),
            )
            self._conn.commit()

    def update_trade(self, trade_id: str, updates: dict) -> None:
        """Update an existing trade record.

        Args:
            trade_id: The trade ID (idempotency key)
            updates: Dict of column -> value to update
        """
        if not updates:
            return
        with self._lock:
            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            self._conn.execute(
                f"UPDATE trades SET {set_clause} WHERE id = ?",
                (*updates.values(), trade_id),
            )
            self._conn.commit()

    def query_trades(
        self,
        ticker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        action: Optional[str] = None,
        min_pnl: Optional[float] = None,
    ) -> List[dict]:
        """Query trades with optional filters.

        Args:
            ticker: Filter by ticker symbol
            start_date: Filter trades created after this ISO date
            end_date: Filter trades created before this ISO date
            action: Filter by action (BUY, SELL, etc.)
            min_pnl: Filter trades with realized_pnl >= this value

        Returns:
            List of trade dicts
        """
        query = "SELECT * FROM trades WHERE 1=1"
        params: List[Any] = []

        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)
        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)
        if action:
            query += " AND action = ?"
            params.append(action)
        if min_pnl is not None:
            query += " AND realized_pnl >= ?"
            params.append(min_pnl)

        query += " ORDER BY created_at DESC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    # ── Decisions ─────────────────────────────────────────────────────

    def insert_decision(self, decision_data: dict) -> None:
        """Insert a decision record.

        Args:
            decision_data: Dict with keys matching decisions table columns.
        """
        with self._lock:
            cols = ", ".join(decision_data.keys())
            placeholders = ", ".join(["?"] * len(decision_data))
            self._conn.execute(
                f"INSERT INTO decisions ({cols}) VALUES ({placeholders})",
                tuple(decision_data.values()),
            )
            self._conn.commit()

    # ── Reflections ───────────────────────────────────────────────────

    def insert_reflection(
        self,
        agent_name: str,
        ticker: Optional[str],
        session_id: Optional[str],
        content: str,
    ) -> None:
        """Insert a reflection record.

        Args:
            agent_name: Name of the agent (bull, bear, trader, etc.)
            ticker: Ticker being analyzed
            session_id: Current session identifier
            content: Reflection narrative text
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO reflections (agent_name, ticker, session_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (agent_name, ticker, session_id, content, datetime.utcnow().isoformat()),
            )
            self._conn.commit()

    def query_reflections(
        self,
        agent_name: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """Query reflections, most recent first.

        Args:
            agent_name: Filter by agent name
            ticker: Filter by ticker
            limit: Max number of results

        Returns:
            List of reflection dicts
        """
        query = "SELECT * FROM reflections WHERE 1=1"
        params: List[Any] = []

        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    # ── Agent Memories (BM25 pairs) ───────────────────────────────────

    def save_memories(
        self,
        agent_name: str,
        pairs: List[Tuple[str, str]],
        ticker: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Save (situation, advice) pairs for BM25 memory.

        situation and advice are stored as SEPARATE columns.

        Args:
            agent_name: Agent identifier (e.g., "bull", "bear")
            pairs: List of (situation, advice) tuples
            ticker: Optional ticker context
            session_id: Current session identifier
        """
        now = datetime.utcnow().isoformat()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO agent_memories (agent_name, ticker, situation, advice, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(agent_name, ticker, sit, adv, session_id, now) for sit, adv in pairs],
            )
            self._conn.commit()

    def load_memories(
        self,
        agent_name: str,
        ticker: Optional[str] = None,
        limit: int = 500,
    ) -> List[Tuple[str, str]]:
        """Load (situation, advice) pairs for BM25 rebuild.

        Args:
            agent_name: Agent identifier
            ticker: Optional filter by ticker
            limit: Max number of pairs to load

        Returns:
            List of (situation, advice) tuples for BM25 index rebuild
        """
        query = "SELECT situation, advice FROM agent_memories WHERE agent_name = ?"
        params: List[Any] = [agent_name]

        if ticker:
            query += " AND ticker = ?"
            params.append(ticker)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            return [(row[0], row[1]) for row in rows]

    # ── Portfolio Snapshots ───────────────────────────────────────────

    def snapshot_portfolio(self, snapshot_data: dict) -> None:
        """Save a portfolio snapshot.

        Args:
            snapshot_data: Dict with keys matching portfolio_snapshots columns.
        """
        with self._lock:
            cols = ", ".join(snapshot_data.keys())
            placeholders = ", ".join(["?"] * len(snapshot_data))
            self._conn.execute(
                f"INSERT INTO portfolio_snapshots ({cols}) VALUES ({placeholders})",
                tuple(snapshot_data.values()),
            )
            self._conn.commit()

    def query_equity_curve(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """Query equity curve from portfolio snapshots.

        Returns:
            List of snapshot dicts, sorted ascending by timestamp
        """
        query = "SELECT * FROM portfolio_snapshots WHERE 1=1"
        params: List[Any] = []

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        query += " ORDER BY timestamp ASC"

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    # ── Rejection Stats ───────────────────────────────────────────────

    def query_rejection_stats(self) -> Dict[str, int]:
        """Get rejection count by rejection_code.

        Returns:
            Dict of rejection_code -> count
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT rejection_code, COUNT(*) as cnt FROM trades "
                "WHERE status = 'REJECTED' AND rejection_code IS NOT NULL "
                "GROUP BY rejection_code"
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    # ── Purge Old Records ─────────────────────────────────────────────

    def purge_old_records(
        self,
        decisions_days: int = 90,
        reflections_days: int = 365,
    ) -> None:
        """Purge old decisions and reflections.

        trades and agent_memories are NEVER deleted.

        Args:
            decisions_days: Delete decisions older than N days
            reflections_days: Delete reflections older than N days
        """
        with self._lock:
            cutoff_decisions = (datetime.utcnow() - timedelta(days=decisions_days)).isoformat()
            cutoff_reflections = (datetime.utcnow() - timedelta(days=reflections_days)).isoformat()

            d_count = self._conn.execute(
                "DELETE FROM decisions WHERE timestamp < ?", (cutoff_decisions,)
            ).rowcount
            r_count = self._conn.execute(
                "DELETE FROM reflections WHERE created_at < ?", (cutoff_reflections,)
            ).rowcount

            self._conn.commit()

            if d_count or r_count:
                logger.info("Purged %d decisions, %d reflections", d_count, r_count)

    # ── Utility ───────────────────────────────────────────────────────

    def get_schema_version(self) -> int:
        """Get current schema version."""
        with self._lock:
            row = self._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row and row[0] else 0

    def get_stats(self) -> Dict[str, int]:
        """Get record counts for all tables."""
        tables = ["trades", "decisions", "reflections", "agent_memories", "portfolio_snapshots"]
        stats = {}
        with self._lock:
            for table in tables:
                row = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                stats[table] = row[0] if row else 0
        return stats

    # ── Entry Price Cache Persistence ─────────────────────────────────

    def upsert_entry_price(
        self, symbol: str, avg_price: float, quantity: float
    ) -> None:
        """Insert or update a cached entry price.

        Args:
            symbol: Trading pair (e.g. 'BTC/USDT')
            avg_price: Weighted average entry price
            quantity: Total position quantity
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO entry_price_cache "
                "(symbol, avg_price, quantity, updated_at) VALUES (?, ?, ?, ?)",
                (symbol, avg_price, quantity, datetime.utcnow().isoformat()),
            )
            self._conn.commit()

    def delete_entry_price(self, symbol: Optional[str] = None) -> None:
        """Delete entry price cache records.

        Args:
            symbol: If provided, delete only this symbol. Otherwise delete all.
        """
        with self._lock:
            if symbol is not None:
                self._conn.execute(
                    "DELETE FROM entry_price_cache WHERE symbol = ?", (symbol,)
                )
            else:
                self._conn.execute("DELETE FROM entry_price_cache")
            self._conn.commit()

    def load_entry_prices(self) -> Dict[str, Tuple[float, float]]:
        """Load all cached entry prices.

        Returns:
            Dict of {symbol: (avg_price, quantity)}
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT symbol, avg_price, quantity FROM entry_price_cache"
            ).fetchall()
            return {row[0]: (row[1], row[2]) for row in rows}
