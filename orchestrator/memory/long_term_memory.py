"""
LongTermMemory — Persistent SQLite store for cross-session memories.

Survives across sessions. Stores structured trading memories such as:
  - Past trade outcomes (profit/loss)
  - Market conditions at decision time
  - Agent performance history

Usage:
    ltm = LongTermMemory(db_path="./data/ltm.db")
    ltm.store_trade_memory(
        ticker="BTCUSDT",
        action="BUY",
        entry_price=65000,
        outcome_pnl=320.5,
        conditions={"rsi": 42, "macd": "bullish"},
        agent_signals={"technical": "BUY", "quant": "BUY"},
    )
    similar = ltm.recall_similar_conditions("BTCUSDT", {"rsi": 40})
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeMemory:
    """A stored record of past trade decision + outcome."""

    memory_id: str
    ticker: str
    action: str            # BUY / SELL / HOLD
    entry_price: float
    outcome_pnl: Optional[float]    # None if trade still open
    conditions: Dict[str, Any]      # Market conditions at decision time
    agent_signals: Dict[str, str]   # agent_id -> signal
    confidence: float
    notes: str
    created_at: datetime
    closed_at: Optional[datetime]

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "ticker": self.ticker,
            "action": self.action,
            "entry_price": self.entry_price,
            "outcome_pnl": self.outcome_pnl,
            "conditions": self.conditions,
            "agent_signals": self.agent_signals,
            "confidence": self.confidence,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class LongTermMemory:
    """
    Cross-session SQLite memory store for trading experience.
    """

    def __init__(self, db_path: str = "./data/ltm.db"):
        import os
        os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup_schema()

    def _setup_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trade_memories (
                memory_id    TEXT PRIMARY KEY,
                ticker       TEXT NOT NULL,
                action       TEXT NOT NULL,
                entry_price  REAL,
                outcome_pnl  REAL,
                conditions   TEXT DEFAULT '{}',
                agent_signals TEXT DEFAULT '{}',
                confidence   REAL DEFAULT 0.5,
                notes        TEXT DEFAULT '',
                created_at   TEXT NOT NULL,
                closed_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tm_ticker ON trade_memories(ticker);
            CREATE INDEX IF NOT EXISTS idx_tm_action ON trade_memories(action);
            CREATE INDEX IF NOT EXISTS idx_tm_created ON trade_memories(created_at);

            CREATE TABLE IF NOT EXISTS agent_performance (
                perf_id    TEXT PRIMARY KEY,
                agent_id   TEXT NOT NULL,
                session_id TEXT,
                correct    INTEGER DEFAULT 0,
                total      INTEGER DEFAULT 0,
                avg_conf   REAL DEFAULT 0.0,
                recorded_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Store ─────────────────────────────────────────────────────────

    def store_trade_memory(
        self,
        ticker: str,
        action: str,
        entry_price: float,
        conditions: Optional[Dict[str, Any]] = None,
        agent_signals: Optional[Dict[str, str]] = None,
        outcome_pnl: Optional[float] = None,
        confidence: float = 0.5,
        notes: str = "",
        memory_id: Optional[str] = None,
    ) -> str:
        """Store a trade decision memory. Returns memory_id."""
        mid = memory_id or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO trade_memories
               (memory_id, ticker, action, entry_price, outcome_pnl,
                conditions, agent_signals, confidence, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                mid, ticker, action, entry_price, outcome_pnl,
                json.dumps(conditions or {}),
                json.dumps(agent_signals or {}),
                confidence, notes, now,
            ),
        )
        self._conn.commit()
        logger.debug("[LTM] Stored trade memory %s: %s %s", mid[:8], action, ticker)
        return mid

    def update_outcome(self, memory_id: str, outcome_pnl: float) -> bool:
        """Update the PnL result after a trade closes."""
        cur = self._conn.execute(
            "UPDATE trade_memories SET outcome_pnl=?, closed_at=? WHERE memory_id=?",
            (outcome_pnl, datetime.utcnow().isoformat(), memory_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── Recall ────────────────────────────────────────────────────────

    def recall_by_ticker(
        self, ticker: str, limit: int = 20, only_profitable: bool = False
    ) -> List[TradeMemory]:
        """Fetch recent memories for a ticker."""
        q = "SELECT * FROM trade_memories WHERE ticker=?"
        params: list = [ticker]
        if only_profitable:
            q += " AND outcome_pnl > 0"
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._row_to_memory(r) for r in self._conn.execute(q, params).fetchall()]

    def recall_by_action(self, action: str, limit: int = 20) -> List[TradeMemory]:
        """Fetch memories filtered by action (BUY/SELL/HOLD)."""
        rows = self._conn.execute(
            "SELECT * FROM trade_memories WHERE action=? ORDER BY created_at DESC LIMIT ?",
            (action.upper(), limit),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def recall_recent(self, limit: int = 10) -> List[TradeMemory]:
        """Fetch the most recent N trade memories."""
        rows = self._conn.execute(
            "SELECT * FROM trade_memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    # ── Performance Stats ─────────────────────────────────────────────

    def record_agent_performance(
        self,
        agent_id: str,
        correct: int,
        total: int,
        avg_confidence: float,
        session_id: Optional[str] = None,
    ) -> None:
        """Record how accurate an agent was in a session."""
        self._conn.execute(
            """INSERT INTO agent_performance
               (perf_id, agent_id, session_id, correct, total, avg_conf, recorded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), agent_id, session_id,
                correct, total, avg_confidence,
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def get_agent_win_rate(self, agent_id: str) -> Dict[str, float]:
        """Return lifetime accuracy stats for an agent."""
        row = self._conn.execute(
            "SELECT SUM(correct) as wins, SUM(total) as total FROM agent_performance WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        wins = row["wins"] or 0
        total = row["total"] or 0
        return {"wins": wins, "total": total, "rate": wins / total if total else 0.0}

    def get_pnl_summary(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Return overall PnL statistics."""
        q = "SELECT COUNT(*) as cnt, SUM(outcome_pnl) as total_pnl, AVG(outcome_pnl) as avg_pnl FROM trade_memories WHERE outcome_pnl IS NOT NULL"
        params = []
        if ticker:
            q += " AND ticker=?"
            params.append(ticker)
        row = self._conn.execute(q, params).fetchone()
        return {
            "trades": row["cnt"] or 0,
            "total_pnl": round(row["total_pnl"] or 0.0, 4),
            "avg_pnl": round(row["avg_pnl"] or 0.0, 4),
        }

    # ── Helpers ───────────────────────────────────────────────────────

    def _row_to_memory(self, row: sqlite3.Row) -> TradeMemory:
        return TradeMemory(
            memory_id=row["memory_id"],
            ticker=row["ticker"],
            action=row["action"],
            entry_price=row["entry_price"],
            outcome_pnl=row["outcome_pnl"],
            conditions=json.loads(row["conditions"] or "{}"),
            agent_signals=json.loads(row["agent_signals"] or "{}"),
            confidence=row["confidence"],
            notes=row["notes"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
        )

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM trade_memories").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
