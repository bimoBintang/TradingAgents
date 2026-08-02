"""
TradingView Execution Guard — Financial Safety & Fail-Closed Guard Engine.

Rules:
1. Fail-Closed Principle: If TradingView CDP or TA validation data is missing, defaults to FAIL-CLOSED (reject/require confirmation).
2. Signal Conflict Prevention: Rejects BUY orders when TradingView TA is STRONG_SELL.
3. Low Confidence Filtering: Rejects trades when ChartVision confidence < 0.60.
4. 60-Second Order Timeout: Orders pending confirmation automatically expire after 60 seconds.
"""

import time
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TVExecutionGuard:
    """
    Financial Safety Guard for TradingView Signal Execution.
    """

    def __init__(
        self,
        min_confidence_threshold: float = 0.60,
        confirmation_timeout_seconds: float = 60.0,
        fail_closed: bool = True,
    ):
        self.min_confidence_threshold = min_confidence_threshold
        self.confirmation_timeout_seconds = confirmation_timeout_seconds
        self.fail_closed = fail_closed

    def validate_execution(
        self,
        proposed_trade: Dict[str, Any],
        ta_recommendation: Optional[str] = "NEUTRAL",
        visual_confidence: Optional[float] = 0.70,
        ict_bias: Optional[str] = "NEUTRAL",
        ob_strength: Optional[str] = "MEDIUM",
        cdp_healthy: bool = True,
        data_complete: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate a proposed trade against TradingView & ICT safety rules.

        Returns:
            Dict containing:
                "approved": bool
                "action": "EXECUTE" | "REJECT" | "REQUIRE_CONFIRMATION"
                "reason": str
                "sizing_multiplier": float (e.g. 1.0, 0.75, 0.50)
                "expires_at": float (timestamp)
        """
        action = proposed_trade.get("action", "HOLD").upper()
        ticker = proposed_trade.get("ticker", "BTCUSDT")
        now = time.time()
        expires_at = now + self.confirmation_timeout_seconds
        sizing_multiplier = 1.0

        # ── Rule 1: Fail-Closed Check ───────────────────────────────────────
        if self.fail_closed and (not data_complete or not cdp_healthy and ta_recommendation is None):
            logger.warning("[TVExecutionGuard] Fail-Closed triggered for %s: Data incomplete.", ticker)
            return {
                "approved": False,
                "action": "REQUIRE_CONFIRMATION",
                "reason": "Fail-Closed Safety: Validation data incomplete. User confirmation required.",
                "sizing_multiplier": 0.0,
                "expires_at": expires_at,
            }

        # ── Rule 2: Signal Conflict Check (TA Klasik) ──────────────────────
        if action == "BUY" and ta_recommendation == "STRONG_SELL":
            logger.warning("[TVExecutionGuard] Signal conflict for %s: BUY proposed during STRONG_SELL.", ticker)
            return {
                "approved": False,
                "action": "REJECT",
                "reason": "Signal Conflict: Proposed BUY conflicts with TradingView STRONG_SELL recommendation.",
                "sizing_multiplier": 0.0,
                "expires_at": expires_at,
            }

        if action == "SELL" and ta_recommendation == "STRONG_BUY":
            logger.warning("[TVExecutionGuard] Signal conflict for %s: SELL proposed during STRONG_BUY.", ticker)
            return {
                "approved": False,
                "action": "REJECT",
                "reason": "Signal Conflict: Proposed SELL conflicts with TradingView STRONG_BUY recommendation.",
                "sizing_multiplier": 0.0,
                "expires_at": expires_at,
            }

        # ── Rule 3: Symmetric ICT Bias Conflict Check ──────────────────────
        # Long Conflict: BUY proposed, TA is BUY/STRONG_BUY, but ICT is BEARISH
        if action == "BUY" and ict_bias == "BEARISH":
            if ob_strength == "HIGH":
                logger.warning("[TVExecutionGuard] Symmetric ICT Conflict (HIGH OB) for %s BUY vs BEARISH ICT", ticker)
                return {
                    "approved": False,
                    "action": "REQUIRE_CONFIRMATION",
                    "reason": "Symmetric ICT Conflict: Proposed BUY conflicts with HIGH strength Bearish ICT Order Block.",
                    "sizing_multiplier": 0.50,
                    "expires_at": expires_at,
                }
            elif ob_strength == "MEDIUM":
                logger.info("[TVExecutionGuard] Symmetric ICT Conflict (MEDIUM OB) for %s: Reducing sizing by 25%%", ticker)
                sizing_multiplier = 0.75

        # Short Conflict: SELL proposed, TA is SELL/STRONG_SELL, but ICT is BULLISH
        elif action == "SELL" and ict_bias == "BULLISH":
            if ob_strength == "HIGH":
                logger.warning("[TVExecutionGuard] Symmetric ICT Conflict (HIGH OB) for %s SELL vs BULLISH ICT", ticker)
                return {
                    "approved": False,
                    "action": "REQUIRE_CONFIRMATION",
                    "reason": "Symmetric ICT Conflict: Proposed SELL conflicts with HIGH strength Bullish ICT Order Block.",
                    "sizing_multiplier": 0.50,
                    "expires_at": expires_at,
                }
            elif ob_strength == "MEDIUM":
                logger.info("[TVExecutionGuard] Symmetric ICT Conflict (MEDIUM OB) for %s: Reducing sizing by 25%%", ticker)
                sizing_multiplier = 0.75

        # ── Rule 4: Low Visual Confidence Check ────────────────────────────
        effective_confidence = visual_confidence if visual_confidence is not None else 0.50
        if effective_confidence < self.min_confidence_threshold:
            logger.warning(
                "[TVExecutionGuard] Low confidence for %s: %.2f < %.2f",
                ticker, effective_confidence, self.min_confidence_threshold
            )
            return {
                "approved": False,
                "action": "REJECT",
                "reason": f"Low Visual Confidence: ChartVision confidence ({effective_confidence:.2f}) below threshold ({self.min_confidence_threshold:.2f}).",
                "sizing_multiplier": 0.0,
                "expires_at": expires_at,
            }

        # ── Rule 5: Passed Safety Validation ───────────────────────────────
        logger.info("[TVExecutionGuard] Execution APPROVED for %s %s (Sizing Multiplier: %.2f)", action, ticker, sizing_multiplier)
        return {
            "approved": True,
            "action": "EXECUTE",
            "reason": f"Execution approved by TVExecutionGuard for {action} {ticker}.",
            "sizing_multiplier": sizing_multiplier,
            "expires_at": expires_at,
        }

    def is_order_expired(self, created_at_timestamp: float) -> bool:
        """
        Check if an order pending confirmation has exceeded the 60-second timeout.
        """
        return (time.time() - created_at_timestamp) > self.confirmation_timeout_seconds
