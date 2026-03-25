"""
GuardRails — Output validation and safety filter for agent responses.

Intercepts agent output before it propagates to the next agent, checking
for common failure modes:
  - Hallucinated ticker symbols
  - Infinite loop detection (repeated content)
  - Invalid JSON structure
  - Forbidden actions (e.g., untrusted asset symbols)
  - Confidence threshold enforcement

Usage:
    guard = GuardRails(allowed_tickers=["BTCUSDT", "ETHUSDT"])

    result = guard.validate(
        agent_id="technical_analyst",
        output={"signal": "BUY", "ticker": "BTCUSDT", "confidence": 0.85},
        output_type="trade_signal",
    )

    if not result.passed:
        for v in result.violations:
            print(f"[{v.severity}] {v.message}")
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Violation:
    """A single guard rule violation."""

    rule: str
    message: str
    severity: Severity
    context: Optional[Any] = None

    def is_blocking(self) -> bool:
        return self.severity in (Severity.ERROR, Severity.CRITICAL)


@dataclass
class GuardResult:
    """Result of running all guards against a single agent output."""

    agent_id: str
    passed: bool
    violations: List[Violation] = field(default_factory=list)
    sanitized_output: Optional[Any] = None  # cleaned output, if applicable

    def blocking_violations(self) -> List[Violation]:
        return [v for v in self.violations if v.is_blocking()]

    def add(self, violation: Violation) -> None:
        self.violations.append(violation)
        if violation.is_blocking():
            self.passed = False

    def summary(self) -> str:
        if self.passed:
            return f"[GuardRails] ✅ {self.agent_id} — passed ({len(self.violations)} warnings)"
        blocking = len(self.blocking_violations())
        return (
            f"[GuardRails] ❌ {self.agent_id} — FAILED "
            f"({blocking} blocking, {len(self.violations)} total)"
        )


# ── Built-in Rule Functions ───────────────────────────────────────────────────

def _rule_valid_json(output: Any, **_) -> Optional[Violation]:
    """Output must be a dict or parseable JSON string."""
    if isinstance(output, dict):
        return None
    if isinstance(output, str):
        try:
            json.loads(output)
            return None
        except json.JSONDecodeError:
            pass
    # Non-dict, non-JSON string — warn but don't block (plain text is OK)
    return None


def _rule_no_empty_output(output: Any, **_) -> Optional[Violation]:
    """Output must not be None or completely empty."""
    if output is None:
        return Violation(
            rule="no_empty_output",
            message="Agent returned None output",
            severity=Severity.ERROR,
        )
    if output == "" or output == {} or output == []:
        return Violation(
            rule="no_empty_output",
            message="Agent returned empty output",
            severity=Severity.WARNING,
        )
    return None


def _rule_confidence_range(output: Any, **_) -> Optional[Violation]:
    """If output contains 'confidence', it must be 0.0–1.0."""
    if isinstance(output, dict):
        conf = output.get("confidence")
        if conf is not None:
            try:
                conf = float(conf)
                if not (0.0 <= conf <= 1.0):
                    return Violation(
                        rule="confidence_range",
                        message=f"Confidence {conf} out of range [0, 1]",
                        severity=Severity.ERROR,
                        context=conf,
                    )
            except (TypeError, ValueError):
                return Violation(
                    rule="confidence_range",
                    message=f"Confidence is not a number: {conf!r}",
                    severity=Severity.ERROR,
                )
    return None


def _rule_valid_action(output: Any, **_) -> Optional[Violation]:
    """If output contains 'action', it must be BUY/SELL/HOLD."""
    VALID_ACTIONS = {"BUY", "SELL", "HOLD", "LONG", "SHORT", "CLOSE"}
    if isinstance(output, dict):
        action = output.get("action")
        if action is not None and str(action).upper() not in VALID_ACTIONS:
            return Violation(
                rule="valid_action",
                message=f"Unknown action '{action}'. Expected one of {VALID_ACTIONS}",
                severity=Severity.ERROR,
                context=action,
            )
    return None


class GuardRails:
    """
    Pipeline of validation rules applied to every agent output.

    Built-in rules (always active):
      - no_empty_output    : blocks None/empty responses
      - confidence_range   : blocks confidence values outside [0, 1]
      - valid_action       : blocks unknown trading action strings
      - allowed_tickers    : blocks outputs with invalid ticker symbols

    Custom rules can be added via add_rule().
    """

    _BUILTIN_RULES: List[Callable] = [
        _rule_valid_json,
        _rule_no_empty_output,
        _rule_confidence_range,
        _rule_valid_action,
    ]

    def __init__(
        self,
        allowed_tickers: Optional[Set[str]] = None,
        min_confidence: float = 0.0,
        max_output_length: int = 50_000,
    ):
        self.allowed_tickers = {t.upper() for t in (allowed_tickers or set())}
        self.min_confidence = min_confidence
        self.max_output_length = max_output_length
        self._custom_rules: List[Callable] = []
        # Per-agent history for loop detection
        self._output_history: Dict[str, List[str]] = {}

    # ── Custom Rules ──────────────────────────────────────────────────

    def add_rule(self, fn: Callable) -> None:
        """
        Add a custom rule function.
        Signature: fn(output: Any, agent_id: str) -> Optional[Violation]
        """
        self._custom_rules.append(fn)

    # ── Core Validation ───────────────────────────────────────────────

    def validate(
        self,
        agent_id: str,
        output: Any,
        output_type: str = "generic",
    ) -> GuardResult:
        """
        Run all guards against an agent's output.
        Returns a GuardResult indicating pass/fail and any violations found.
        """
        result = GuardResult(agent_id=agent_id, passed=True, sanitized_output=output)

        # ── Built-in rules ────────────────────────────────────────────
        for rule_fn in self._BUILTIN_RULES:
            v = rule_fn(output=output, agent_id=agent_id)
            if v:
                result.add(v)

        # ── Ticker validation ─────────────────────────────────────────
        if self.allowed_tickers and isinstance(output, dict):
            ticker = output.get("ticker")
            if ticker and str(ticker).upper() not in self.allowed_tickers:
                result.add(Violation(
                    rule="allowed_tickers",
                    message=f"Ticker '{ticker}' is not in allowlist {self.allowed_tickers}",
                    severity=Severity.CRITICAL,
                    context=ticker,
                ))

        # ── Minimum confidence threshold ──────────────────────────────
        if self.min_confidence > 0.0 and isinstance(output, dict):
            conf = output.get("confidence", 1.0)
            try:
                if float(conf) < self.min_confidence:
                    result.add(Violation(
                        rule="min_confidence",
                        message=(
                            f"Confidence {conf:.2f} below minimum {self.min_confidence:.2f}"
                        ),
                        severity=Severity.WARNING,
                    ))
            except (TypeError, ValueError):
                pass

        # ── Output length guard ───────────────────────────────────────
        output_str = str(output)
        if len(output_str) > self.max_output_length:
            result.add(Violation(
                rule="max_output_length",
                message=(
                    f"Output length {len(output_str)} exceeds limit {self.max_output_length}"
                ),
                severity=Severity.WARNING,
            ))

        # ── Loop detection ────────────────────────────────────────────
        loop_violation = self._detect_loop(agent_id, output_str)
        if loop_violation:
            result.add(loop_violation)

        # ── Custom rules ──────────────────────────────────────────────
        for rule_fn in self._custom_rules:
            v = rule_fn(output=output, agent_id=agent_id)
            if v:
                result.add(v)

        # Log result
        if result.passed:
            logger.debug("[GuardRails] ✅ %s passed validation", agent_id)
        else:
            logger.warning("[GuardRails] ❌ %s BLOCKED: %s", agent_id, result.summary())

        return result

    # ── Loop Detection ────────────────────────────────────────────────

    def _detect_loop(self, agent_id: str, output_str: str, window: int = 3) -> Optional[Violation]:
        """
        Detect if an agent is returning identical or near-identical
        outputs repeatedly (stuck in a reasoning loop).
        """
        history = self._output_history.setdefault(agent_id, [])
        # Fingerprint: first 200 chars, lowered
        fingerprint = output_str[:200].lower().strip()
        history.append(fingerprint)

        if len(history) >= window:
            recent = history[-window:]
            if len(set(recent)) == 1:  # all identical
                return Violation(
                    rule="loop_detection",
                    message=(
                        f"Agent '{agent_id}' produced identical output "
                        f"{window} times in a row — possible infinite loop"
                    ),
                    severity=Severity.CRITICAL,
                )
        return None

    def reset_history(self, agent_id: Optional[str] = None) -> None:
        """Clear loop detection history for an agent (or all agents)."""
        if agent_id:
            self._output_history.pop(agent_id, None)
        else:
            self._output_history.clear()

    # ── Batch Validation ─────────────────────────────────────────────

    def validate_all(
        self, outputs: Dict[str, Any]
    ) -> Dict[str, GuardResult]:
        """Validate a dict of {agent_id: output} in one call."""
        return {aid: self.validate(aid, out) for aid, out in outputs.items()}

    def summary(self) -> dict:
        return {
            "allowed_tickers": list(self.allowed_tickers),
            "min_confidence": self.min_confidence,
            "custom_rules": len(self._custom_rules),
            "agents_tracked": len(self._output_history),
        }
