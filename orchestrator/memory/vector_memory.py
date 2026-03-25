"""
VectorMemory — Lightweight vector database using SQLite-Vec.

Stores embedding vectors alongside metadata for semantic search.
No Docker required — runs purely on SQLite with the sqlite-vec extension.

Usage:
    mem = VectorMemory(db_path="./data/vectors.db", dimensions=128)
    entry_id = mem.store("btc_pattern_001", vector, {"ticker": "BTC", "action": "BUY"})
    results = mem.search(query_vector, top_k=5)
"""

import json
import logging
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fallback if sqlite_vec is unavailable: use pure cosine similarity on a list
try:
    import sqlite_vec
    SQLITE_VEC_AVAILABLE = True
except ImportError:
    SQLITE_VEC_AVAILABLE = False
    logger.warning(
        "[VectorMemory] sqlite-vec not installed. Falling back to in-memory cosine search. "
        "Install with: pip install sqlite-vec"
    )

import sqlite3


@dataclass
class VectorEntry:
    """A stored vector with associated metadata."""

    entry_id: str
    label: str
    vector: List[float]
    metadata: Dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)
    score: Optional[float] = None  # populated after a search

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "score": self.score,
        }


# ── Helper functions ──────────────────────────────────────────────────────────

def _pack_vector(v: List[float]) -> bytes:
    """Pack float list to little-endian IEEE 754 bytes."""
    return struct.pack(f"{len(v)}f", *v)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Pure-Python cosine similarity."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class VectorMemory:
    """
    Persistent vector database backed by SQLite.

    When sqlite-vec is installed, uses the native HNSW index for
    fast approximate nearest-neighbour search. Falls back to a
    brute-force cosine search stored in a plain SQLite table.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        dimensions: int = 128,
        table_name: str = "vectors",
    ):
        self.db_path = db_path
        self.dimensions = dimensions
        self.table_name = table_name
        self._conn = self._setup_db()

    def _setup_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        if SQLITE_VEC_AVAILABLE:
            try:
                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS {self.table_name}
                    USING vec0(
                        entry_id TEXT PRIMARY KEY,
                        embedding FLOAT[{self.dimensions}]
                    )
                """)
            except (AttributeError, Exception) as e:
                # Python compiled without extension loading support → use brute force
                logger.warning(
                    "[VectorMemory] sqlite-vec extension unavailable (%s). "
                    "Using brute-force cosine search.", e
                )
                # Patch flag so rest of code uses fallback path
                import orchestrator.memory.vector_memory as _self_mod
                _self_mod.SQLITE_VEC_AVAILABLE = False
        # Always create metadata table
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name}_meta (
                entry_id    TEXT PRIMARY KEY,
                label       TEXT NOT NULL,
                metadata    TEXT DEFAULT '{{}}',
                raw_vector  BLOB,
                created_at  TEXT
            )
        """)
        conn.commit()
        return conn

    # ── Store ─────────────────────────────────────────────────────────

    def store(
        self,
        label: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        entry_id: Optional[str] = None,
    ) -> str:
        """Store a vector with metadata. Returns the entry_id."""
        if len(vector) != self.dimensions:
            raise ValueError(
                f"Vector has {len(vector)} dims, expected {self.dimensions}"
            )
        eid = entry_id or str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        meta_json = json.dumps(metadata or {})
        raw = _pack_vector(vector)

        if SQLITE_VEC_AVAILABLE:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {self.table_name}(entry_id, embedding) VALUES (?, ?)",
                (eid, raw),
            )
        self._conn.execute(
            f"""INSERT OR REPLACE INTO {self.table_name}_meta
                (entry_id, label, metadata, raw_vector, created_at)
                VALUES (?, ?, ?, ?, ?)""",
            (eid, label, meta_json, raw, now),
        )
        self._conn.commit()
        logger.debug("[VectorMemory] Stored '%s' (id=%s)", label, eid[:8])
        return eid

    # ── Search ────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[VectorEntry]:
        """Return top-k most similar entries to query_vector."""
        if SQLITE_VEC_AVAILABLE:
            return self._search_sqlite_vec(query_vector, top_k, min_score)
        return self._search_brute_force(query_vector, top_k, min_score)

    def _search_sqlite_vec(
        self, query: List[float], top_k: int, min_score: float
    ) -> List[VectorEntry]:
        raw_q = _pack_vector(query)
        rows = self._conn.execute(
            f"""
            SELECT v.entry_id, v.distance, m.label, m.metadata, m.raw_vector, m.created_at
            FROM {self.table_name} v
            JOIN {self.table_name}_meta m ON v.entry_id = m.entry_id
            WHERE embedding MATCH ? AND k = ?
            ORDER BY distance
            """,
            (raw_q, top_k),
        ).fetchall()
        results = []
        for row in rows:
            meta = json.loads(row["metadata"])
            raw = row["raw_vector"]
            vec = list(struct.unpack(f"{self.dimensions}f", raw)) if raw else []
            score = 1.0 - float(row["distance"])  # convert L2 to similarity
            if score >= min_score:
                results.append(VectorEntry(
                    entry_id=row["entry_id"],
                    label=row["label"],
                    vector=vec,
                    metadata=meta,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    score=score,
                ))
        return results

    def _search_brute_force(
        self, query: List[float], top_k: int, min_score: float
    ) -> List[VectorEntry]:
        rows = self._conn.execute(
            f"SELECT entry_id, label, metadata, raw_vector, created_at FROM {self.table_name}_meta"
        ).fetchall()
        scored = []
        for row in rows:
            raw = row["raw_vector"]
            if not raw:
                continue
            vec = list(struct.unpack(f"{self.dimensions}f", raw))
            score = _cosine_similarity(query, vec)
            if score >= min_score:
                meta = json.loads(row["metadata"])
                scored.append((score, VectorEntry(
                    entry_id=row["entry_id"],
                    label=row["label"],
                    vector=vec,
                    metadata=meta,
                    created_at=datetime.fromisoformat(row["created_at"]),
                    score=score,
                )))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    # ── Delete / List ─────────────────────────────────────────────────

    def delete(self, entry_id: str) -> bool:
        cur = self._conn.execute(
            f"DELETE FROM {self.table_name}_meta WHERE entry_id = ?", (entry_id,)
        )
        if SQLITE_VEC_AVAILABLE:
            self._conn.execute(
                f"DELETE FROM {self.table_name} WHERE entry_id = ?", (entry_id,)
            )
        self._conn.commit()
        return cur.rowcount > 0

    def list_all(self, limit: int = 100) -> List[VectorEntry]:
        rows = self._conn.execute(
            f"SELECT entry_id, label, metadata, created_at FROM {self.table_name}_meta LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            VectorEntry(
                entry_id=r["entry_id"],
                label=r["label"],
                vector=[],
                metadata=json.loads(r["metadata"]),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def count(self) -> int:
        return self._conn.execute(
            f"SELECT COUNT(*) FROM {self.table_name}_meta"
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()
