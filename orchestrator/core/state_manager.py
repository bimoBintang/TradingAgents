"""
StateManager — Shared session state for all agents.

All agents can read and write to a shared state object during
a single analysis session. State is isolated per session_id and
categorized into namespaces for clarity.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Immutable snapshot of a session's state at a point in time."""

    session_id: str
    ticker: str
    created_at: datetime
    namespaces: Dict[str, Dict[str, Any]]  # namespace -> key -> value
    agent_outputs: Dict[str, Any]           # agent_id -> output
    decisions: List[Dict[str, Any]]          # list of proposed trade decisions
    metadata: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "ticker": self.ticker,
            "created_at": self.created_at.isoformat(),
            "namespaces": self.namespaces,
            "agent_outputs": self.agent_outputs,
            "decisions": self.decisions,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class StateManager:
    """
    Thread-safe shared state store for a single orchestration session.

    State is organized into namespaces to avoid collisions:
        - 'market'   : raw price/OHLCV data, indicators
        - 'analysis' : reports from each analyst agent
        - 'risk'     : risk scores, position sizing
        - 'consensus': final agreed upon decision

    Usage:
        state = StateManager(session_id="abc123", ticker="BTCUSDT")

        # Analyst writes its report
        state.set("analysis", "technical_report", {"signal": "BUY", ...})

        # Risk manager reads analyst reports
        report = state.get("analysis", "technical_report")

        # Store final decision
        state.add_decision({"action": "BUY", "confidence": 0.87, ...})
    """

    VALID_NAMESPACES = {"market", "analysis", "risk", "consensus", "custom"}

    def __init__(
        self,
        ticker: str,
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.ticker = ticker
        self.created_at = datetime.utcnow()
        self._namespaces: Dict[str, Dict[str, Any]] = {
            ns: {} for ns in self.VALID_NAMESPACES
        }
        self._agent_outputs: Dict[str, Any] = {}
        self._decisions: List[Dict[str, Any]] = []
        self._metadata: Dict[str, Any] = metadata or {}
        self._write_log: List[dict] = []

    # ── Read / Write ──────────────────────────────────────────────────

    def set(self, namespace: str, key: str, value: Any, writer: str = "system") -> None:
        """Write a value to a namespace key."""
        ns = self._resolve_namespace(namespace)
        ns[key] = value
        entry = {
            "namespace": namespace,
            "key": key,
            "writer": writer,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._write_log.append(entry)
        logger.debug("[State] %s.%s written by '%s'", namespace, key, writer)

    def get(self, namespace: str, key: str, default: Any = None) -> Any:
        """Read a value from a namespace key."""
        ns = self._resolve_namespace(namespace)
        return ns.get(key, default)

    def get_namespace(self, namespace: str) -> Dict[str, Any]:
        """Return all key-value pairs in a namespace."""
        return dict(self._resolve_namespace(namespace))

    def update(self, namespace: str, updates: Dict[str, Any], writer: str = "system") -> None:
        """Bulk-update multiple keys in a namespace."""
        for k, v in updates.items():
            self.set(namespace, k, v, writer=writer)

    def _resolve_namespace(self, namespace: str) -> Dict[str, Any]:
        if namespace not in self._namespaces:
            logger.warning("[State] Unknown namespace '%s', using 'custom'", namespace)
            return self._namespaces["custom"]
        return self._namespaces[namespace]

    # ── Agent Outputs ─────────────────────────────────────────────────

    def record_agent_output(self, agent_id: str, output: Any) -> None:
        """Store the final output of a specific agent."""
        self._agent_outputs[agent_id] = {
            "output": output,
            "recorded_at": datetime.utcnow().isoformat(),
        }
        logger.debug("[State] Output recorded for agent '%s'", agent_id)

    def get_agent_output(self, agent_id: str) -> Optional[Any]:
        """Retrieve the recorded output of a specific agent."""
        entry = self._agent_outputs.get(agent_id)
        return entry["output"] if entry else None

    def get_all_agent_outputs(self) -> Dict[str, Any]:
        """Return all recorded agent outputs."""
        return {aid: entry["output"] for aid, entry in self._agent_outputs.items()}

    # ── Decisions ─────────────────────────────────────────────────────

    def add_decision(self, decision: Dict[str, Any]) -> None:
        """Append a proposed trade decision to the session's decision list."""
        decision.setdefault("proposed_at", datetime.utcnow().isoformat())
        self._decisions.append(decision)
        logger.info(
            "[State] Decision added: %s %s (confidence: %.2f)",
            decision.get("action", "?"),
            self.ticker,
            decision.get("confidence", 0.0),
        )

    def get_decisions(self) -> List[Dict[str, Any]]:
        """Return all proposed decisions for this session."""
        return list(self._decisions)

    def get_final_decision(self) -> Optional[Dict[str, Any]]:
        """Return the last (most authoritative) decision if any."""
        return self._decisions[-1] if self._decisions else None

    # ── Snapshot / Serialization ──────────────────────────────────────

    def snapshot(self) -> SessionState:
        """Return an immutable snapshot of the current state."""
        return SessionState(
            session_id=self.session_id,
            ticker=self.ticker,
            created_at=self.created_at,
            namespaces={ns: dict(d) for ns, d in self._namespaces.items()},
            agent_outputs=dict(self._agent_outputs),
            decisions=list(self._decisions),
            metadata=dict(self._metadata),
        )

    def summary(self) -> dict:
        """Return a brief human-readable summary."""
        return {
            "session_id": self.session_id,
            "ticker": self.ticker,
            "age_seconds": (datetime.utcnow() - self.created_at).total_seconds(),
            "namespaces": {
                ns: len(d) for ns, d in self._namespaces.items() if d
            },
            "agents_reported": list(self._agent_outputs.keys()),
            "decisions_count": len(self._decisions),
            "writes": len(self._write_log),
        }
