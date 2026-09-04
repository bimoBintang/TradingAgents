"""Durability tests for risk-control state (Blocker 2).

The SaaS API builds a NEW TradingAgentsGraph — and therefore a new
RiskController — for every analysis run. Before this state was persisted,
that meant the kill switch, the consecutive-loss counter, and the rolling
PnL window that triggers the drawdown limits all reset to zero before each
decision: a halt never survived to block the next trade.

These tests assert the state actually crosses instance boundaries, stays
isolated per account, and fails CLOSED when the store is unreadable.
"""

import os
import tempfile
from datetime import datetime, timedelta

import pytest

from tradingagents.execution.risk_controls import RiskController
from tradingagents.storage.database import Database


@pytest.fixture
def db():
    path = os.path.join(tempfile.mkdtemp(), "risk_test.db")
    database = Database(path)
    yield database
    database.close()


def rc(db, account_id="user_1", **kwargs):
    return RiskController(db=db, account_id=account_id, **kwargs)


class TestKillSwitchDurability:
    def test_survives_a_new_controller_instance(self, db):
        rc(db).activate_kill_switch("Daily loss limit breached")
        restored = rc(db)
        assert restored.is_kill_switch_active is True
        assert "Daily loss limit" in restored._kill_switch_reason

    def test_deactivation_also_persists(self, db):
        rc(db).activate_kill_switch("halt")
        rc(db).deactivate_kill_switch()
        assert rc(db).is_kill_switch_active is False

    def test_activation_date_survives_for_auto_recovery(self, db):
        rc(db).activate_kill_switch("halt")
        restored = rc(db)
        assert restored._kill_switch_activated_date == datetime.utcnow().date()

    def test_restored_halt_blocks_a_new_controller(self, db):
        # The whole point: the NEXT analysis must still be halted.
        rc(db).activate_kill_switch("Daily loss limit breached")
        assert rc(db).is_kill_switch_active is True


class TestConsecutiveLossDurability:
    def test_loss_streak_survives(self, db):
        c = rc(db)
        c.record_trade_result(-100.0, "BTC")
        c.record_trade_result(-50.0, "BTC")
        assert rc(db)._consecutive_losses == 2

    def test_a_win_resets_the_streak_and_persists(self, db):
        c = rc(db)
        c.record_trade_result(-100.0, "BTC")
        c.record_trade_result(-100.0, "BTC")
        c.record_trade_result(+250.0, "BTC")
        assert rc(db)._consecutive_losses == 0

    def test_last_loss_time_survives(self, db):
        rc(db).record_trade_result(-100.0, "BTC")
        assert rc(db)._last_loss_time is not None


class TestPnLWindowDurability:
    """The window is the drawdown TRIGGER — persisting only the kill-switch
    flag would leave the limits permanently unable to fire."""

    def test_daily_pnl_survives(self, db):
        c = rc(db)
        c.record_trade_result(-500.0, "BTC")
        c.record_trade_result(-300.0, "ETH")
        assert rc(db)._pnl_tracker.daily_pnl == pytest.approx(-800.0)

    def test_drawdown_is_computable_from_restored_state(self, db):
        c = rc(db)
        c.record_trade_result(-800.0, "BTC")
        drawdowns = rc(db)._pnl_tracker.get_drawdowns(total_equity=10_000.0)
        assert drawdowns.get("daily") == pytest.approx(0.08)

    def test_mixed_results_net_out(self, db):
        c = rc(db)
        c.record_trade_result(-500.0, "BTC")
        c.record_trade_result(+200.0, "ETH")
        assert rc(db)._pnl_tracker.daily_pnl == pytest.approx(-300.0)

    def test_malformed_rows_do_not_destroy_the_window(self, db):
        from tradingagents.execution.risk_controls import _PnLTracker
        t = _PnLTracker()
        t.load_state([
            {"pnl": -100.0, "timestamp": datetime.utcnow().isoformat()},
            {"pnl": "not-a-number", "timestamp": "garbage"},
            {"pnl": -50.0, "timestamp": datetime.utcnow().isoformat()},
        ])
        assert t.daily_pnl == pytest.approx(-150.0)

    def test_entries_older_than_30_days_are_dropped(self, db):
        from tradingagents.execution.risk_controls import _PnLTracker
        t = _PnLTracker()
        t.load_state([
            {"pnl": -1000.0, "timestamp": (datetime.utcnow() - timedelta(days=45)).isoformat()},
            {"pnl": -100.0, "timestamp": datetime.utcnow().isoformat()},
        ])
        assert t.monthly_pnl == pytest.approx(-100.0)


class TestAccountIsolation:
    """One shared database file must not mean one shared kill switch."""

    def test_halt_does_not_leak_to_another_account(self, db):
        rc(db, "user_1").activate_kill_switch("user_1 breached limit")
        assert rc(db, "user_2").is_kill_switch_active is False

    def test_loss_streaks_are_independent(self, db):
        a = rc(db, "user_1")
        a.record_trade_result(-100.0, "BTC")
        a.record_trade_result(-100.0, "BTC")
        rc(db, "user_2").record_trade_result(-100.0, "BTC")
        assert rc(db, "user_1")._consecutive_losses == 2
        assert rc(db, "user_2")._consecutive_losses == 1

    def test_pnl_windows_are_independent(self, db):
        rc(db, "user_1").record_trade_result(-900.0, "BTC")
        assert rc(db, "user_2")._pnl_tracker.daily_pnl == 0.0


class TestFailureModes:
    def test_unreadable_store_fails_closed(self):
        # If we cannot tell whether trading was halted, the safe assumption
        # is that it WAS. Failing open here would resume trading precisely
        # when the system is least healthy.
        class BrokenDB:
            def load_risk_state(self, account_id):
                raise RuntimeError("disk unavailable")

        c = RiskController(db=BrokenDB(), account_id="user_1")
        assert c.is_kill_switch_active is True
        assert "fail-closed" in c._kill_switch_reason.lower()

    def test_unwritable_store_does_not_crash_the_decision(self, db):
        # Losing persistence is bad, but aborting an in-flight risk
        # evaluation because of it would be worse.
        class HalfBrokenDB:
            def load_risk_state(self, account_id):
                return None
            def save_risk_state(self, **kwargs):
                raise RuntimeError("disk full")

        c = RiskController(db=HalfBrokenDB(), account_id="user_1")
        c.activate_kill_switch("halt")          # must not raise
        c.record_trade_result(-100.0, "BTC")    # must not raise
        assert c.is_kill_switch_active is True

    def test_works_without_a_database(self):
        # Library/CLI use with no storage configured must still function,
        # just without durability.
        c = RiskController()
        c.activate_kill_switch("halt")
        assert c.is_kill_switch_active is True

    def test_corrupt_activation_date_keeps_the_halt(self, db):
        db.save_risk_state(
            account_id="user_1", kill_switch=True, kill_switch_reason="halt",
            kill_switch_activated_date="not-a-date", consecutive_losses=0,
            last_loss_time=None, pnl_window_json="[]",
        )
        c = rc(db)
        # An unparseable date must not silently drop the halt.
        assert c.is_kill_switch_active is True
        assert c._kill_switch_activated_date is not None


class TestDatabaseLayer:
    def test_absent_account_returns_none(self, db):
        assert db.load_risk_state("never_seen") is None

    def test_save_is_an_upsert(self, db):
        for reason in ("first", "second"):
            db.save_risk_state(
                account_id="u", kill_switch=True, kill_switch_reason=reason,
                kill_switch_activated_date=None, consecutive_losses=1,
                last_loss_time=None, pnl_window_json="[]",
            )
        assert db.load_risk_state("u")["kill_switch_reason"] == "second"

    def test_schema_upgrade_is_idempotent(self, db):
        Database(db.db_path).close()   # re-open and re-migrate
        assert db.load_risk_state("anything") is None
