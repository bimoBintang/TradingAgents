"""
CircuitBreaker — Automatic kill switch for agents and orchestration runs.

Inspired by the electrical circuit breaker pattern: when a component
fails repeatedly, the circuit "opens" and blocks further calls until
a cooldown period passes.

Three states:
  CLOSED  → Normal operation, calls allowed
  OPEN    → Failed too many times, calls blocked
  HALF_OPEN → Cooldown complete, one trial call allowed

Additionally provides:
  - Portfolio drawdown breaker (halts trading if losses exceed threshold)
  - Timeout sentry (marks agent as failed if it doesn't complete in time)
  - Global kill switch (manual emergency stop)

Usage:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=60)

    try:
        cb.call("risk_agent", risky_function, arg1, arg2)
    except CircuitOpenError:
        print("Circuit is OPEN — agent is blocked")
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is attempted on an open circuit."""
    pass


class DrawdownBreachedError(Exception):
    """Raised when portfolio drawdown exceeds the configured threshold."""
    pass


class KillSwitchError(Exception):
    """Raised when the global emergency kill switch is active."""
    pass


@dataclass
class CircuitStats:
    """Operational stats for a single circuit."""

    name: str
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    successes: int = 0
    last_failure_at: Optional[float] = None
    last_success_at: Optional[float] = None
    opened_at: Optional[float] = None
    total_calls: int = 0


class CircuitBreaker:
    """
    Per-agent and global circuit breaker for the orchestration platform.

    Features:
      - Per-agent circuits with failure counting and auto-reset
      - Portfolio drawdown breaker
      - Global emergency kill switch

    Usage:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=60)

        # Wrap a function call
        result = cb.call("my_agent", my_function, arg1=val1)

        # Or use as async context manager
        async with cb.async_call("my_agent", my_coro):
            pass

        # Portfolio safety
        cb.record_pnl(-0.15)          # -15% loss
        cb.check_drawdown(limit=-0.10) # raises DrawdownBreachedError

        # Emergency stop
        cb.kill()                      # blocks ALL future calls
        cb.revive()                    # re-enable
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: float = 60.0,   # seconds before OPEN → HALF_OPEN
        success_threshold: int = 1,    # successes in HALF_OPEN to close circuit
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold

        self._circuits: Dict[str, CircuitStats] = {}
        self._kill_switch: bool = False
        self._cumulative_pnl: float = 0.0
        self._peak_pnl: float = 0.0

    # ── Circuit State Machine ─────────────────────────────────────────

    def _get_or_create(self, name: str) -> CircuitStats:
        if name not in self._circuits:
            self._circuits[name] = CircuitStats(name=name)
        return self._circuits[name]

    def _transition(self, stats: CircuitStats, new_state: CircuitState) -> None:
        old = stats.state
        stats.state = new_state
        if new_state == CircuitState.OPEN:
            stats.opened_at = time.monotonic()
        logger.info(
            "[CircuitBreaker] '%s' %s → %s (failures=%d)",
            stats.name, old.value, new_state.value, stats.failures,
        )

    def _check_state(self, stats: CircuitStats) -> None:
        """Update state based on timing and failure count."""
        if stats.state == CircuitState.OPEN:
            elapsed = time.monotonic() - (stats.opened_at or 0)
            if elapsed >= self.reset_timeout:
                self._transition(stats, CircuitState.HALF_OPEN)
        elif stats.state == CircuitState.HALF_OPEN:
            pass  # will resolve on next success/failure

    def is_open(self, name: str) -> bool:
        """Return True if the circuit for 'name' is OPEN (blocking calls)."""
        stats = self._get_or_create(name)
        self._check_state(stats)
        return stats.state == CircuitState.OPEN

    def get_state(self, name: str) -> CircuitState:
        stats = self._get_or_create(name)
        self._check_state(stats)
        return stats.state

    # ── Synchronous Call Wrapper ──────────────────────────────────────

    def call(self, name: str, fn: Callable, *args, **kwargs) -> Any:
        """
        Call fn(*args, **kwargs) protected by the circuit named 'name'.
        Raises CircuitOpenError if circuit is OPEN.
        Raises KillSwitchError if global kill switch is active.
        """
        self._check_kill_switch()
        stats = self._get_or_create(name)
        self._check_state(stats)
        stats.total_calls += 1

        if stats.state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit '{name}' is OPEN. Retry after {self.reset_timeout}s cooldown."
            )

        try:
            result = fn(*args, **kwargs)
            self._on_success(stats)
            return result
        except Exception as exc:
            self._on_failure(stats, exc)
            raise

    async def async_call(self, name: str, coro, *args, **kwargs) -> Any:
        """Async version of call() for coroutines."""
        self._check_kill_switch()
        stats = self._get_or_create(name)
        self._check_state(stats)
        stats.total_calls += 1

        if stats.state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit '{name}' is OPEN. Retry after {self.reset_timeout}s cooldown."
            )

        try:
            if asyncio.iscoroutine(coro):
                result = await coro
            else:
                result = await coro(*args, **kwargs)
            self._on_success(stats)
            return result
        except Exception as exc:
            self._on_failure(stats, exc)
            raise

    # ── Success / Failure Handlers ────────────────────────────────────

    def _on_success(self, stats: CircuitStats) -> None:
        stats.successes += 1
        stats.last_success_at = time.monotonic()

        if stats.state == CircuitState.HALF_OPEN:
            if stats.successes >= self.success_threshold:
                stats.failures = 0
                self._transition(stats, CircuitState.CLOSED)

    def _on_failure(self, stats: CircuitStats, exc: Exception) -> None:
        stats.failures += 1
        stats.last_failure_at = time.monotonic()
        logger.warning(
            "[CircuitBreaker] '%s' failure #%d: %s",
            stats.name, stats.failures, exc,
        )

        if stats.state == CircuitState.HALF_OPEN:
            # Immediately re-open on failure in half-open
            self._transition(stats, CircuitState.OPEN)
        elif stats.failures >= self.failure_threshold:
            self._transition(stats, CircuitState.OPEN)

    # ── Manual Circuit Controls ───────────────────────────────────────

    def reset(self, name: str) -> None:
        """Manually reset (close) a circuit."""
        stats = self._get_or_create(name)
        stats.failures = 0
        stats.successes = 0
        stats.opened_at = None
        self._transition(stats, CircuitState.CLOSED)

    def force_open(self, name: str, reason: str = "") -> None:
        """Manually force a circuit open (e.g. during maintenance)."""
        stats = self._get_or_create(name)
        logger.warning("[CircuitBreaker] '%s' forced OPEN: %s", name, reason)
        self._transition(stats, CircuitState.OPEN)

    # ── Kill Switch ───────────────────────────────────────────────────

    def kill(self, reason: str = "Emergency stop activated") -> None:
        """Activate the global kill switch — blocks ALL agent calls."""
        self._kill_switch = True
        logger.critical("[CircuitBreaker] 🔴 GLOBAL KILL SWITCH ACTIVATED: %s", reason)

    def revive(self) -> None:
        """Deactivate the kill switch and restore normal operation."""
        self._kill_switch = False
        logger.info("[CircuitBreaker] 🟢 Kill switch deactivated — resuming operation")

    def _check_kill_switch(self) -> None:
        if self._kill_switch:
            raise KillSwitchError("Global kill switch is active. All agent calls are blocked.")

    # ── Portfolio Drawdown Breaker ────────────────────────────────────

    def record_pnl(self, pnl_delta: float) -> None:
        """
        Record a PnL change (positive = profit, negative = loss).
        Updates internal peak and cumulative tracking.
        """
        self._cumulative_pnl += pnl_delta
        if self._cumulative_pnl > self._peak_pnl:
            self._peak_pnl = self._cumulative_pnl

    def current_drawdown(self) -> float:
        """
        Return the current drawdown as a negative fraction.
        e.g. -0.15 means 15% drawdown from peak.
        """
        if self._peak_pnl <= 0:
            return 0.0
        dd = (self._cumulative_pnl - self._peak_pnl) / self._peak_pnl
        return round(dd, 4)

    def check_drawdown(self, limit: float = -0.10) -> None:
        """
        Raise DrawdownBreachedError if current drawdown exceeds 'limit'.
        limit should be negative (e.g. -0.10 = halt if 10% drawdown).
        """
        dd = self.current_drawdown()
        if dd <= limit:
            logger.critical(
                "[CircuitBreaker] 🔴 DRAWDOWN BREACH: %.2f%% ≤ limit %.2f%%",
                dd * 100, limit * 100,
            )
            raise DrawdownBreachedError(
                f"Drawdown {dd:.2%} exceeded limit {limit:.2%}. Trading halted."
            )

    # ── Inspection ────────────────────────────────────────────────────

    def get_stats(self, name: str) -> dict:
        stats = self._get_or_create(name)
        self._check_state(stats)
        return {
            "name": name,
            "state": stats.state.value,
            "failures": stats.failures,
            "successes": stats.successes,
            "total_calls": stats.total_calls,
        }

    def all_stats(self) -> Dict[str, dict]:
        return {name: self.get_stats(name) for name in self._circuits}

    def summary(self) -> dict:
        open_circuits = [n for n, s in self._circuits.items() if s.state == CircuitState.OPEN]
        return {
            "kill_switch": self._kill_switch,
            "total_circuits": len(self._circuits),
            "open_circuits": open_circuits,
            "cumulative_pnl": self._cumulative_pnl,
            "drawdown": f"{self.current_drawdown():.2%}",
        }
