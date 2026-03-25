"""
ShortTermMemory — In-memory key-value store for active session context.

Acts like a fast, ephemeral scratchpad for agents. Data is lost
when the session ends (by design). Supports TTL-based expiry,
conversation history, and typed namespaces.
"""

import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Sentinel to distinguish "key not found" from a stored None
_MISSING = object()


class ShortTermMemory:
    """
    Fast in-memory scratchpad for a single agent session.

    Features:
      - TTL-based automatic expiry
      - Conversation history ring buffer
      - Namespace isolation

    Usage:
        stm = ShortTermMemory(ttl_seconds=300)
        stm.set("price", 65_432.0)
        stm.push_message("user", "What is the Bitcoin price?")

        price = stm.get("price")          # 65432.0
        history = stm.get_history()       # [{"role": "user", ...}]
    """

    def __init__(
        self,
        ttl_seconds: float = 3600.0,
        max_history: int = 50,
        namespace: str = "default",
    ):
        self.ttl_seconds = ttl_seconds
        self.max_history = max_history
        self.namespace = namespace

        # key -> (value, expire_at)
        self._store: Dict[str, Tuple[Any, float]] = {}
        # Conversation history ring buffer
        self._history: Deque[Dict[str, Any]] = deque(maxlen=max_history)
        # Context variables (never expire)
        self._context: Dict[str, Any] = {}

    # ── Key-Value Store ───────────────────────────────────────────────

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
    ) -> None:
        """Store a value with optional custom TTL (seconds)."""
        expire_at = time.monotonic() + (ttl if ttl is not None else self.ttl_seconds)
        self._store[key] = (value, expire_at)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value, returning default if expired or missing."""
        entry = self._store.get(key, _MISSING)
        if entry is _MISSING:
            return default
        value, expire_at = entry
        if time.monotonic() > expire_at:
            del self._store[key]
            return default
        return value

    def delete(self, key: str) -> bool:
        return self._store.pop(key, _MISSING) is not _MISSING

    def exists(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def keys(self) -> List[str]:
        """Return all non-expired keys."""
        now = time.monotonic()
        return [k for k, (_, exp) in list(self._store.items()) if now <= exp]

    def expire_all(self) -> int:
        """Evict expired entries. Returns count of removed items."""
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    def clear(self) -> None:
        self._store.clear()
        self._history.clear()
        self._context.clear()

    # ── Conversation History ──────────────────────────────────────────

    def push_message(self, role: str, content: str, extra: Optional[dict] = None) -> None:
        """Append a message to the conversation history ring buffer."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            **(extra or {}),
        }
        self._history.append(msg)

    def get_history(self, last_n: Optional[int] = None) -> List[dict]:
        """Return conversation history (newest last)."""
        history = list(self._history)
        return history[-last_n:] if last_n else history

    def get_history_as_prompt(self) -> str:
        """Format history as a single string for LLM prompt injection."""
        lines = []
        for msg in self._history:
            lines.append(f"[{msg['role'].upper()}]: {msg['content']}")
        return "\n".join(lines)

    # ── Context Variables (Permanent for Session) ─────────────────────

    def set_context(self, key: str, value: Any) -> None:
        """Set a context variable that never expires."""
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    # ── Summary ───────────────────────────────────────────────────────

    def summary(self) -> dict:
        self.expire_all()
        return {
            "namespace": self.namespace,
            "active_keys": len(self._store),
            "history_messages": len(self._history),
            "context_keys": len(self._context),
            "ttl_seconds": self.ttl_seconds,
        }
