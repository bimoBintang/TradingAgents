"""Regression tests for the two defects that made TVExecutionGuard undeployable.

Both were found while deciding whether to wire the guard into the live
execution path (README claimed it was already there; nothing called it).
Neither is hypothetical — each fires on the configuration this project
actually runs in, where TradingView Desktop is usually not running.
"""

import pytest

from orchestrator.guards.tv_execution_guard import TVExecutionGuard


BUY = {"action": "BUY", "ticker": "BTC/USDT"}


@pytest.fixture
def guard():
    return TVExecutionGuard(min_confidence_threshold=0.60, fail_closed=True)


class TestFailClosedPrecedence:
    """`and` bound tighter than `or`, inverting the rule this guard is named for."""

    def test_dead_cdp_does_not_execute_just_because_ta_exists(self, guard):
        # The original grouping was:
        #   not data_complete or (not cdp_healthy and ta_recommendation is None)
        # so a present TA string rescued a dead CDP link and returned EXECUTE.
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.90,
            cdp_healthy=False, data_complete=True,
        )
        assert result["approved"] is False
        assert result["action"] == "REQUIRE_CONFIRMATION"
        assert result["sizing_multiplier"] == 0.0

    def test_incomplete_data_fails_closed(self, guard):
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.90,
            cdp_healthy=True, data_complete=False,
        )
        assert result["approved"] is False

    def test_missing_ta_fails_closed(self, guard):
        result = guard.validate_execution(
            BUY, ta_recommendation=None, visual_confidence=0.90,
            cdp_healthy=True, data_complete=True,
        )
        assert result["approved"] is False

    def test_fail_closed_disabled_lets_the_other_rules_decide(self):
        open_guard = TVExecutionGuard(fail_closed=False)
        result = open_guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.90,
            cdp_healthy=False, data_complete=False,
        )
        assert result["approved"] is True


class TestUnavailableDataIsNotLowConfidence:
    """`None` means no model ran; it must not be reported as a 0.50 score."""

    def test_absent_vision_is_not_reported_as_a_number(self, guard):
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=None,
        )
        assert result["approved"] is False
        # The old code said "confidence (0.50) below threshold" — a score
        # no model ever produced.
        assert "0.50" not in result["reason"]
        assert "unavailable" in result["reason"].lower()

    def test_absent_vision_asks_for_confirmation_not_rejection(self, guard):
        # REJECT is a verdict on the trade; the guard has no basis for one.
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=None,
        )
        assert result["action"] == "REQUIRE_CONFIRMATION"

    def test_a_real_low_score_is_still_rejected(self, guard):
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.42,
        )
        assert result["approved"] is False
        assert result["action"] == "REJECT"
        assert "0.42" in result["reason"]

    def test_a_real_high_score_still_passes(self, guard):
        result = guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.90,
        )
        assert result["approved"] is True
        assert result["sizing_multiplier"] == 1.0

    def test_threshold_boundary_is_inclusive(self, guard):
        assert guard.validate_execution(
            BUY, ta_recommendation="BUY", visual_confidence=0.60,
        )["approved"] is True


class TestGuardIsNotWiredIn:
    """Documents the claim the README used to make. Delete when it is wired."""

    def test_execution_engine_does_not_import_the_guard(self):
        import inspect
        from tradingagents.execution import execution_engine

        source = inspect.getsource(execution_engine)
        assert "TVExecutionGuard" not in source, (
            "The guard now appears in the execution engine. If it was "
            "deliberately wired in, update README and delete this test — "
            "but first confirm its inputs exist at execution time, or it "
            "will reject every trade."
        )
