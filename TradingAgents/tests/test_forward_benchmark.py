"""Tests for forward agent-vs-baseline measurement.

The value of this harness rests entirely on fairness: every strategy must
be recorded at the same instant, same entry price, same horizon, same
costs — otherwise the comparison silently favours one of them. These tests
pin that fairness down, plus the sample-size gate that stops a handful of
resolved decisions being read as a verdict.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api.database import SessionLocal
from api.models import BenchmarkDecision, User
from api.services import forward_benchmark as fb


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def user(db):
    # Unique email per test: a shared fixed address means one failed
    # teardown poisons every subsequent run with a UNIQUE violation that
    # looks nothing like the real problem.
    u = User(
        email=f"__test_fwd_bench_{uuid.uuid4().hex[:12]}__@example.com",
        name="t",
        hashed_password="x",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    try:
        db.query(BenchmarkDecision).filter(BenchmarkDecision.user_id == u.id).delete()
        db.query(User).filter(User.id == u.id).delete()
        db.commit()
    except Exception:
        db.rollback()


def rising_closes(n=60):
    return [100.0 + i for i in range(n)]


class TestRecording:
    def test_records_agent_and_all_baselines(self, db, user):
        with patch.object(fb, "_recent_closes", return_value=rising_closes()):
            written = fb.record_decision_set(db, user.id, "TEST", "BUY", 0.9)

        assert written >= 3, "agent + at least two baselines"
        rows = db.query(BenchmarkDecision).filter(BenchmarkDecision.user_id == user.id).all()
        strategies = {r.strategy for r in rows}
        assert fb.AGENT_STRATEGY in strategies
        assert "buy_and_hold" in strategies
        assert "sma_20_50" in strategies

    def test_all_strategies_share_entry_price_and_horizon(self, db, user):
        with patch.object(fb, "_recent_closes", return_value=rising_closes()):
            fb.record_decision_set(db, user.id, "TEST", "BUY", 0.9)

        rows = db.query(BenchmarkDecision).filter(BenchmarkDecision.user_id == user.id).all()
        assert len({r.entry_price for r in rows}) == 1, "one price for everyone, or it isn't a fair test"
        assert len({r.horizon_days for r in rows}) == 1

    def test_strong_buy_is_normalized(self, db, user):
        with patch.object(fb, "_recent_closes", return_value=rising_closes()):
            fb.record_decision_set(db, user.id, "TEST", "STRONG_BUY", 0.95)
        agent = db.query(BenchmarkDecision).filter(
            BenchmarkDecision.user_id == user.id,
            BenchmarkDecision.strategy == fb.AGENT_STRATEGY,
        ).one()
        assert agent.action == "BUY"

    def test_missing_price_records_nothing_at_all(self, db, user):
        # A partial record would score the agent while leaving baselines
        # unscored — worse than no data.
        with patch.object(fb, "_recent_closes", return_value=[]):
            written = fb.record_decision_set(db, user.id, "TEST", "BUY", 0.9)
        assert written == 0
        assert db.query(BenchmarkDecision).filter(BenchmarkDecision.user_id == user.id).count() == 0


class TestBaselineActions:
    def test_buy_and_hold_is_always_long(self):
        assert fb._baseline_actions(rising_closes())["buy_and_hold"] == "BUY"

    def test_sma_goes_long_in_uptrend(self):
        assert fb._baseline_actions(rising_closes(60))["sma_20_50"] == "BUY"

    def test_sma_is_flat_in_downtrend(self):
        falling = [200.0 - i for i in range(60)]
        assert fb._baseline_actions(falling)["sma_20_50"] == "HOLD"

    def test_sma_holds_without_enough_history(self):
        assert fb._baseline_actions([100.0] * 10)["sma_20_50"] == "HOLD"


class TestResolution:
    def _record(self, db, user, action, entry=100.0, days_ago=0, horizon=5):
        row = BenchmarkDecision(
            user_id=user.id, strategy="agent", ticker="TEST", action=action,
            entry_price=entry, horizon_days=horizon,
            decided_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_does_not_resolve_before_horizon(self, db, user):
        self._record(db, user, "BUY", days_ago=1, horizon=5)
        with patch.object(fb, "_current_price", return_value=110.0):
            assert fb.resolve_due(db) == 0

    def test_resolves_after_horizon(self, db, user):
        row = self._record(db, user, "BUY", entry=100.0, days_ago=6, horizon=5)
        with patch.object(fb, "_current_price", return_value=110.0):
            assert fb.resolve_due(db) == 1
        db.refresh(row)
        assert row.resolved is True
        # +10% move, minus the 0.30% round-trip cost
        assert row.return_pct == pytest.approx(10.0 - fb.DEFAULT_COST_PCT)

    def test_short_profits_when_price_falls(self, db, user):
        row = self._record(db, user, "SELL", entry=100.0, days_ago=6)
        with patch.object(fb, "_current_price", return_value=90.0):
            fb.resolve_due(db)
        db.refresh(row)
        assert row.return_pct == pytest.approx(10.0 - fb.DEFAULT_COST_PCT)

    def test_hold_takes_no_position_and_pays_no_cost(self, db, user):
        row = self._record(db, user, "HOLD", entry=100.0, days_ago=6)
        with patch.object(fb, "_current_price", return_value=150.0):
            fb.resolve_due(db)
        db.refresh(row)
        assert row.return_pct == 0.0

    def test_resolution_is_idempotent(self, db, user):
        self._record(db, user, "BUY", days_ago=6)
        with patch.object(fb, "_current_price", return_value=110.0):
            assert fb.resolve_due(db) == 1
            assert fb.resolve_due(db) == 0

    def test_unavailable_price_leaves_row_pending(self, db, user):
        row = self._record(db, user, "BUY", days_ago=6)
        with patch.object(fb, "_current_price", return_value=None):
            assert fb.resolve_due(db) == 0
        db.refresh(row)
        assert row.resolved is False


class TestComparison:
    def _bulk(self, db, user, strategy, action, return_pct, count):
        for _ in range(count):
            db.add(BenchmarkDecision(
                user_id=user.id, strategy=strategy, ticker="TEST", action=action,
                entry_price=100.0, exit_price=100.0 * (1 + return_pct / 100.0),
                return_pct=return_pct, resolved=True,
                decided_at=datetime.now(timezone.utc) - timedelta(days=10),
                resolved_at=datetime.now(timezone.utc),
            ))
        db.commit()

    def test_aggregates_per_strategy(self, db, user):
        self._bulk(db, user, "agent", "BUY", 2.0, 25)
        self._bulk(db, user, "buy_and_hold", "BUY", 1.0, 25)
        c = fb.build_comparison(db, user.id)
        assert set(c["strategies"]) == {"agent", "buy_and_hold"}
        assert c["strategies"]["agent"]["positions_taken"] == 25
        assert c["strategies"]["agent"]["win_rate_pct"] == 100.0

    def test_returns_compound(self, db, user):
        self._bulk(db, user, "agent", "BUY", 10.0, 2)
        c = fb.build_comparison(db, user.id)
        # 1.10^2 = 1.21 -> +21%, not a flat +20% sum
        assert c["strategies"]["agent"]["total_return_pct"] == pytest.approx(21.0, abs=1e-6)

    def test_hold_decisions_do_not_dilute_returns(self, db, user):
        self._bulk(db, user, "agent", "BUY", 5.0, 20)
        self._bulk(db, user, "agent", "HOLD", 0.0, 30)
        c = fb.build_comparison(db, user.id)
        assert c["strategies"]["agent"]["decisions"] == 50
        assert c["strategies"]["agent"]["positions_taken"] == 20
        assert c["strategies"]["agent"]["avg_return_pct"] == pytest.approx(5.0)

    def test_verdict_refuses_to_call_it_on_small_samples(self, db, user):
        self._bulk(db, user, "agent", "BUY", 50.0, 3)
        self._bulk(db, user, "buy_and_hold", "BUY", 1.0, 3)
        assert "Too early" in fb.build_comparison(db, user.id)["verdict"]

    def test_verdict_when_agent_wins(self, db, user):
        self._bulk(db, user, "agent", "BUY", 3.0, 25)
        self._bulk(db, user, "buy_and_hold", "BUY", 1.0, 25)
        assert "leads" in fb.build_comparison(db, user.id)["verdict"]

    def test_verdict_when_agent_loses(self, db, user):
        self._bulk(db, user, "agent", "BUY", 0.5, 25)
        self._bulk(db, user, "buy_and_hold", "BUY", 3.0, 25)
        verdict = fb.build_comparison(db, user.id)["verdict"]
        assert "trails" in verdict
        assert "not currently paying for its" in verdict

    def test_needs_both_agent_and_a_baseline(self, db, user):
        self._bulk(db, user, "agent", "BUY", 2.0, 25)
        assert "Not enough data" in fb.build_comparison(db, user.id)["verdict"]

    def test_report_renders(self, db, user):
        self._bulk(db, user, "agent", "BUY", 2.0, 25)
        self._bulk(db, user, "sma_20_50", "BUY", 1.0, 25)
        report = fb.format_comparison_report(fb.build_comparison(db, user.id))
        assert "Forward Benchmark" in report
        assert "agent" in report
        assert "Verdict" in report
