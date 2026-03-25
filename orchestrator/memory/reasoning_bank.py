"""
ReasoningBank — Self-learning pattern storage for agent decisions.

Stores successful (and failed) reasoning trajectories, allowing
the orchestrator to retrieve similar past decisions when faced
with new market conditions. Inspired by Ruflo's ReasoningBank,
built purely in Python + SQLite.

A "trajectory" = one full reasoning cycle:
  task → context → reasoning steps → outcome → score

Usage:
    bank = ReasoningBank(db_path="./data/reasoning.db")

    # Record a successful analysis trajectory
    tid = bank.start_trajectory("Analyze BTCUSDT for BUY signal")
    bank.add_step(tid, "observation", "RSI is 38 — oversold territory")
    bank.add_step(tid, "reasoning", "Historical bounce rate at RSI<40: 72%")
    bank.add_step(tid, "action", "Recommend BUY with 0.82 confidence")
    bank.finalize(tid, score=0.9, outcome="Trade closed +$320 PnL")

    # Retrieve similar patterns for future decisions
    suggestions = bank.suggest("BTCUSDT RSI oversold signal")
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TrajectoryStep:
    step_type: str    # "observation" | "reasoning" | "action" | "reflection"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TrajectoryRecord:
    """A complete reasoning trajectory with its outcome."""

    trajectory_id: str
    task: str
    steps: List[TrajectoryStep]
    score: float              # 0.0 (bad) to 1.0 (perfect)
    outcome: str
    tags: List[str]
    created_at: datetime
    finalized_at: Optional[datetime]

    def to_dict(self) -> dict:
        return {
            "trajectory_id": self.trajectory_id,
            "task": self.task,
            "steps": [{"type": s.step_type, "content": s.content} for s in self.steps],
            "score": self.score,
            "outcome": self.outcome,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "finalized_at": self.finalized_at.isoformat() if self.finalized_at else None,
        }

    def as_context_string(self) -> str:
        """Format trajectory as a concise string for LLM prompt injection."""
        lines = [f"[Pattern: {self.task}] Score={self.score:.2f}"]
        for step in self.steps:
            lines.append(f"  [{step.step_type.upper()}] {step.content}")
        lines.append(f"  [OUTCOME] {self.outcome}")
        return "\n".join(lines)


class ReasoningBank:
    """
    Self-learning pattern repository.

    Records agent reasoning trajectories and surfaces the most
    relevant past patterns when given a new query. Uses keyword
    matching + score weighting for retrieval (extensible to vector
    search via VectorMemory if needed).
    """

    def __init__(self, db_path: str = ":memory:"):
        import os
        if db_path != ":memory:" and "/" in db_path:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup_schema()
        # In-progress trajectories (before finalize)
        self._active: Dict[str, Dict[str, Any]] = {}

    def _setup_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trajectories (
                trajectory_id TEXT PRIMARY KEY,
                task          TEXT NOT NULL,
                steps         TEXT DEFAULT '[]',
                score         REAL DEFAULT 0.5,
                outcome       TEXT DEFAULT '',
                tags          TEXT DEFAULT '[]',
                created_at    TEXT NOT NULL,
                finalized_at  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_traj_score ON trajectories(score DESC);
            CREATE INDEX IF NOT EXISTS idx_traj_task  ON trajectories(task);

            CREATE TABLE IF NOT EXISTS distilled_patterns (
                pattern_id  TEXT PRIMARY KEY,
                summary     TEXT NOT NULL,
                source_ids  TEXT DEFAULT '[]',
                confidence  REAL DEFAULT 0.5,
                created_at  TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Trajectory Lifecycle ──────────────────────────────────────────

    def start_trajectory(
        self, task: str, tags: Optional[List[str]] = None
    ) -> str:
        """Begin a new reasoning trajectory. Returns trajectory_id."""
        tid = str(uuid.uuid4())
        self._active[tid] = {
            "task": task,
            "steps": [],
            "tags": tags or [],
            "created_at": datetime.utcnow().isoformat(),
        }
        logger.debug("[ReasoningBank] Started trajectory %s: %s", tid[:8], task)
        return tid

    def add_step(
        self,
        trajectory_id: str,
        step_type: str,
        content: str,
    ) -> None:
        """Append a reasoning step to an active trajectory."""
        if trajectory_id not in self._active:
            logger.warning("[ReasoningBank] Trajectory %s not found", trajectory_id[:8])
            return
        self._active[trajectory_id]["steps"].append({
            "step_type": step_type,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def finalize(
        self,
        trajectory_id: str,
        score: float,
        outcome: str = "",
        extra_tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Finalize a trajectory with a quality score (0.0–1.0) and
        persist it to SQLite. Returns True on success.
        """
        if trajectory_id not in self._active:
            logger.warning("[ReasoningBank] Cannot finalize unknown trajectory %s", trajectory_id[:8])
            return False

        traj = self._active.pop(trajectory_id)
        tags = traj["tags"] + (extra_tags or [])
        now = datetime.utcnow().isoformat()

        self._conn.execute(
            """INSERT OR REPLACE INTO trajectories
               (trajectory_id, task, steps, score, outcome, tags, created_at, finalized_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                trajectory_id,
                traj["task"],
                json.dumps(traj["steps"]),
                max(0.0, min(1.0, score)),
                outcome,
                json.dumps(tags),
                traj["created_at"],
                now,
            ),
        )
        self._conn.commit()
        logger.info(
            "[ReasoningBank] Finalized %s | score=%.2f | '%s'",
            trajectory_id[:8], score, traj["task"][:60],
        )
        return True

    # ── Retrieval ─────────────────────────────────────────────────────

    def suggest(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.5,
    ) -> List[TrajectoryRecord]:
        """
        Retrieve top-k most relevant past trajectories for a given query.

        Scoring: keyword overlap × stored quality score.
        """
        query_words = set(query.lower().split())
        rows = self._conn.execute(
            "SELECT * FROM trajectories WHERE score >= ? AND finalized_at IS NOT NULL ORDER BY score DESC LIMIT 50",
            (min_score,),
        ).fetchall()

        scored = []
        for row in rows:
            task_words = set(row["task"].lower().split())
            overlap = len(query_words & task_words) / max(len(query_words), 1)
            relevance = overlap * float(row["score"])
            scored.append((relevance, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, row in scored[:top_k]:
            steps_raw = json.loads(row["steps"] or "[]")
            results.append(TrajectoryRecord(
                trajectory_id=row["trajectory_id"],
                task=row["task"],
                steps=[TrajectoryStep(**s) for s in steps_raw],
                score=row["score"],
                outcome=row["outcome"],
                tags=json.loads(row["tags"] or "[]"),
                created_at=datetime.fromisoformat(row["created_at"]),
                finalized_at=(
                    datetime.fromisoformat(row["finalized_at"])
                    if row["finalized_at"] else None
                ),
            ))
        logger.debug(
            "[ReasoningBank] suggest('%s') → %d results", query[:50], len(results)
        )
        return results

    def suggest_as_prompt(self, query: str, top_k: int = 3) -> str:
        """Return suggestions formatted as an LLM-ready context string."""
        trajectories = self.suggest(query, top_k=top_k)
        if not trajectories:
            return ""
        lines = ["[PAST REASONING PATTERNS — Use these as reference, not gospel]"]
        for i, traj in enumerate(trajectories, 1):
            lines.append(f"\n--- Pattern {i} (quality={traj.score:.2f}) ---")
            lines.append(traj.as_context_string())
        return "\n".join(lines)

    # ── Distillation ──────────────────────────────────────────────────

    def distill(self, min_count: int = 3, min_score: float = 0.7) -> int:
        """
        Summarize high-quality recurring patterns into distilled entries.
        Returns number of patterns distilled.
        """
        rows = self._conn.execute(
            "SELECT task, COUNT(*) as cnt, AVG(score) as avg_score, GROUP_CONCAT(trajectory_id) as ids "
            "FROM trajectories WHERE score >= ? GROUP BY task HAVING cnt >= ?",
            (min_score, min_count),
        ).fetchall()

        count = 0
        for row in rows:
            pid = str(uuid.uuid4())
            self._conn.execute(
                "INSERT OR IGNORE INTO distilled_patterns (pattern_id, summary, source_ids, confidence, created_at) VALUES (?,?,?,?,?)",
                (
                    pid,
                    f"[Distilled] {row['task']}",
                    row["ids"],
                    float(row["avg_score"]),
                    datetime.utcnow().isoformat(),
                ),
            )
            count += 1
        self._conn.commit()
        logger.info("[ReasoningBank] Distilled %d patterns", count)
        return count

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) as total, AVG(score) as avg_score, MAX(score) as max_score FROM trajectories"
        ).fetchone()
        return {
            "total_trajectories": row["total"] or 0,
            "avg_score": round(row["avg_score"] or 0, 3),
            "max_score": round(row["max_score"] or 0, 3),
            "active_sessions": len(self._active),
            "distilled_patterns": self._conn.execute(
                "SELECT COUNT(*) FROM distilled_patterns"
            ).fetchone()[0],
        }

    def close(self) -> None:
        self._conn.close()
