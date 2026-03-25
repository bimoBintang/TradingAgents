"""
TokenMeter — API token usage tracking and budget enforcement.

Models like Claude-3.5-Sonnet charge per input/output token.
TokenMeter tracks every LLM call, calculates cost, and raises
warnings (or halts) when a session budget is exceeded.

Pricing defaults are for Anthropic Claude-3.5-Sonnet (as of 2025).
Override via set_pricing() as needed.

Usage:
    meter = TokenMeter(session_budget_usd=0.50)

    # After each LLM call:
    meter.record(
        agent_id="technical_analyst",
        model="claude-3-5-sonnet",
        input_tokens=1200,
        output_tokens=350,
    )

    print(meter.session_cost_usd)   # e.g. 0.0048
    meter.check_budget()            # raises BudgetExceeded if over limit
"""

import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when token spending exceeds the session budget."""
    pass


# ── Default pricing per 1M tokens (USD) ──────────────────────────────────────

DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku":  {"input": 0.80, "output":  4.00},
    "claude-3-opus":     {"input": 15.00, "output": 75.00},
    "gpt-4o":            {"input": 5.00, "output": 15.00},
    "gpt-4o-mini":       {"input": 0.15, "output":  0.60},
    "gemini-1.5-pro":    {"input": 1.25, "output":  5.00},
    "default":           {"input": 3.00, "output": 15.00},
}


@dataclass
class UsageRecord:
    """A single LLM call's token usage entry."""

    record_id: str
    session_id: str
    agent_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    recorded_at: datetime

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "recorded_at": self.recorded_at.isoformat(),
        }


class TokenMeter:
    """
    Session-level token usage tracker with budget enforcement.

    Stores usage in SQLite for persistence and historical analysis.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        session_budget_usd: float = 1.00,
        db_path: str = ":memory:",
        warn_at_pct: float = 0.80,   # warn when 80% of budget used
    ):
        self.session_id = session_id or str(uuid.uuid4())[:10]
        self.session_budget_usd = session_budget_usd
        self.warn_at_pct = warn_at_pct
        self._pricing = dict(DEFAULT_PRICING)
        self._conn = self._setup_db(db_path)
        self._warned = False

    def _setup_db(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_usage (
                record_id     TEXT PRIMARY KEY,
                session_id    TEXT NOT NULL,
                agent_id      TEXT NOT NULL,
                model         TEXT NOT NULL,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd      REAL DEFAULT 0.0,
                recorded_at   TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tu_session ON token_usage(session_id)")
        conn.commit()
        return conn

    # ── Pricing ───────────────────────────────────────────────────────

    def set_pricing(self, model: str, input_per_1m: float, output_per_1m: float) -> None:
        """Override cost per 1M tokens for a specific model."""
        self._pricing[model] = {"input": input_per_1m, "output": output_per_1m}

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = self._pricing.get(model, self._pricing["default"])
        input_cost  = (input_tokens  / 1_000_000) * prices["input"]
        output_cost = (output_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost

    # ── Recording ─────────────────────────────────────────────────────

    def record(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        model: str = "claude-3-5-sonnet",
        session_id: Optional[str] = None,
    ) -> UsageRecord:
        """Record an LLM call's token usage. Returns the UsageRecord."""
        sid = session_id or self.session_id
        cost = self._calculate_cost(model, input_tokens, output_tokens)
        rid = str(uuid.uuid4())
        now = datetime.utcnow()

        self._conn.execute(
            """INSERT INTO token_usage
               (record_id, session_id, agent_id, model, input_tokens, output_tokens, cost_usd, recorded_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (rid, sid, agent_id, model, input_tokens, output_tokens, cost, now.isoformat()),
        )
        self._conn.commit()

        record = UsageRecord(
            record_id=rid, session_id=sid, agent_id=agent_id, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost, recorded_at=now,
        )

        logger.debug(
            "[TokenMeter] %s | %s | in=%d out=%d | $%.6f",
            agent_id, model, input_tokens, output_tokens, cost,
        )

        # Budget checks
        total = self.session_cost_usd
        warn_threshold = self.session_budget_usd * self.warn_at_pct
        if not self._warned and total >= warn_threshold:
            logger.warning(
                "[TokenMeter] ⚠️  Session '%s' used $%.4f / $%.4f (%.0f%% of budget)",
                self.session_id, total, self.session_budget_usd,
                (total / self.session_budget_usd) * 100,
            )
            self._warned = True

        return record

    def check_budget(self) -> None:
        """Raise BudgetExceeded if the session budget has been surpassed."""
        total = self.session_cost_usd
        if total > self.session_budget_usd:
            raise BudgetExceeded(
                f"Session '{self.session_id}' spent ${total:.4f}, "
                f"exceeding budget of ${self.session_budget_usd:.4f}"
            )

    # ── Queries ───────────────────────────────────────────────────────

    @property
    def session_cost_usd(self) -> float:
        """Total cost for the current session."""
        row = self._conn.execute(
            "SELECT SUM(cost_usd) FROM token_usage WHERE session_id=?",
            (self.session_id,),
        ).fetchone()
        return row[0] or 0.0

    @property
    def session_tokens(self) -> Dict[str, int]:
        """Total input/output tokens for the current session."""
        row = self._conn.execute(
            "SELECT SUM(input_tokens), SUM(output_tokens) FROM token_usage WHERE session_id=?",
            (self.session_id,),
        ).fetchone()
        return {"input": row[0] or 0, "output": row[1] or 0}

    def get_by_agent(self, agent_id: str) -> Dict[str, float]:
        """Return usage breakdown for a specific agent in this session."""
        row = self._conn.execute(
            "SELECT SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
            "FROM token_usage WHERE session_id=? AND agent_id=?",
            (self.session_id, agent_id),
        ).fetchone()
        return {
            "input_tokens": row[0] or 0,
            "output_tokens": row[1] or 0,
            "cost_usd": round(row[2] or 0.0, 6),
        }

    def get_history(self, limit: int = 50) -> List[UsageRecord]:
        """Return most recent usage records for this session."""
        rows = self._conn.execute(
            "SELECT * FROM token_usage WHERE session_id=? ORDER BY recorded_at DESC LIMIT ?",
            (self.session_id, limit),
        ).fetchall()
        return [
            UsageRecord(
                record_id=r["record_id"], session_id=r["session_id"],
                agent_id=r["agent_id"], model=r["model"],
                input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
                cost_usd=r["cost_usd"],
                recorded_at=datetime.fromisoformat(r["recorded_at"]),
            )
            for r in rows
        ]

    def top_spenders(self, top_n: int = 5) -> List[Dict]:
        """Return agents sorted by cost descending."""
        rows = self._conn.execute(
            "SELECT agent_id, SUM(cost_usd) as total FROM token_usage "
            "WHERE session_id=? GROUP BY agent_id ORDER BY total DESC LIMIT ?",
            (self.session_id, top_n),
        ).fetchall()
        return [{"agent_id": r["agent_id"], "cost_usd": round(r["total"], 6)} for r in rows]

    def summary(self) -> dict:
        tokens = self.session_tokens
        cost = self.session_cost_usd
        budget = self.session_budget_usd
        return {
            "session_id": self.session_id,
            "total_cost_usd": f"${cost:.4f}",
            "budget_usd": f"${budget:.4f}",
            "budget_used_pct": f"{(cost / budget * 100):.1f}%" if budget else "N/A",
            "input_tokens": tokens["input"],
            "output_tokens": tokens["output"],
            "total_tokens": tokens["input"] + tokens["output"],
        }
