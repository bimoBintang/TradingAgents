"""Autopilot: goals, tick behaviour, controls, and the force_confirmation fix. DB in memory, LLM never called."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.models import Base, PortfolioState, TaskResult, Trade
from api.services import autopilot as A


@pytest.fixture
def env(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(A, "SessionLocal", Session)
    import api.database
    monkeypatch.setattr(api.database, "SessionLocal", Session)
    calls = []

    def fake_do_analysis(task_id, user_id, ticker, trade_date, auto_execute, force_confirmation=False):
        calls.append(ticker)
        with Session() as db:
            t = db.query(TaskResult).filter_by(task_id=task_id).first()
            t.status = "completed"
            t.result_json = json.dumps({"decision": json.dumps({"action": "BUY", "confidence_score": 0.7,
                                                                 "reasoning": "because"}), "order_result": None})
            db.commit()
    import api.tasks
    monkeypatch.setattr(api.tasks, "_do_analysis", fake_do_analysis)
    return NS(Session=Session, calls=calls)


def _setup(env, watchlist=("BTC-USD",), **sched):
    from api.user_context import save_user_config
    with env.Session() as db:
        owner = A.get_or_create_owner(db)
        save_user_config(db, owner.id, {"scheduler": {"watchlist": list(watchlist), "interval_minutes": 60, **sched}})
        return owner.id


def _set_equity(env, uid, value):
    with env.Session() as db:
        ps = db.query(PortfolioState).filter_by(user_id=uid).first()
        ps.total_equity = value
        db.commit()


# ── pure goals ────────────────────────────────────────────────────────

def test_evaluate_goals():
    ap = {"start_equity": 1000.0, "target_profit_pct": 10, "max_loss_pct": 5}
    assert A.evaluate_goals(ap, 1050) is None
    assert A.evaluate_goals(ap, 1100) == "target_profit"
    assert A.evaluate_goals(ap, 950) == "max_loss"
    assert A.evaluate_goals({**ap, "target_profit_pct": None, "max_loss_pct": None}, 5000) is None
    end = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert A.evaluate_goals({"end_at": end}, 1) == "end_at"
    assert A.evaluate_goals({"end_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, 1) is None


# ── tick ──────────────────────────────────────────────────────────────

def test_disabled_does_nothing(env):
    _setup(env)
    assert A.run_tick() == {"skipped": "disabled"}
    assert env.calls == []


def test_start_then_tick_analyzes_once_per_interval(env):
    _setup(env, watchlist=("BTC-USD", "ETH-USD"))
    with env.Session() as db:
        st = A.start(db, target_profit_pct=10, max_loss_pct=5)
    assert st["enabled"] and st["state"] == "running" and st["progress"]["start_equity"] == 100000.0
    assert A.run_tick()["ran"] == ["BTC-USD", "ETH-USD"]
    assert A.run_tick()["ran"] == []          # inside the interval: nothing due
    assert env.calls == ["BTC-USD", "ETH-USD"]


@pytest.mark.parametrize("equity,reason", [(110000.0, "target_profit"), (94000.0, "max_loss")])
def test_goal_reached_stops_and_runs_nothing(env, equity, reason):
    uid = _setup(env)
    with env.Session() as db:
        A.start(db, target_profit_pct=10, max_loss_pct=5)
    _set_equity(env, uid, equity)
    assert A.run_tick() == {"stopped": reason}
    assert env.calls == []
    with env.Session() as db:
        st = A.status(db)
    assert st["enabled"] is False and st["state"] == "stopped" and st["stopped_reason"] == reason


def test_end_at_stops(env):
    _setup(env)
    with env.Session() as db:
        A.start(db, end_at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
    assert A.run_tick(now=datetime.now(timezone.utc) + timedelta(minutes=5)) == {"stopped": "end_at"}
    assert env.calls == []


def test_enabled_from_config_gets_a_baseline(env):
    uid = _setup(env, enabled=True)
    A.run_tick()
    with env.Session() as db:
        st = A.status(db)
    assert st["progress"]["start_equity"] == 100000.0 and st["state"] == "running"


def test_pause_keeps_baseline_and_resume_after_stop_is_refused(env):
    uid = _setup(env)
    with env.Session() as db:
        A.start(db, target_profit_pct=10)
        assert A.pause(db)["state"] == "paused"
        assert A.resume(db)["progress"]["start_equity"] == 100000.0
    _set_equity(env, uid, 120000.0)
    A.run_tick()
    with env.Session() as db, pytest.raises(ValueError):
        A.resume(db)


def test_max_trades_per_day_and_running_task_and_lock(env):
    uid = _setup(env, max_trades_per_day=1)
    with env.Session() as db:
        A.start(db)
        ps = db.query(PortfolioState).filter_by(user_id=uid).first()
        db.add(Trade(portfolio_id=ps.id, ticker="BTC-USD", action="BUY", filled_qty=1, fill_price=1,
                     status="FILLED", fill_time=datetime.now(timezone.utc)))
        db.commit()
    assert A.run_tick()["ran"] == []           # daily cap reached

    uid2 = _setup(env, max_trades_per_day=10)
    with env.Session() as db:
        db.add(TaskResult(task_id="x", user_id=uid2, ticker="BTC-USD", status="running"))
        db.commit()
    assert A.run_tick() == {"skipped": "an analysis is already running"}

    A._tick_lock.acquire()
    try:
        assert A.run_tick() == {"skipped": "tick already running"}
    finally:
        A._tick_lock.release()


def test_closed_market_is_skipped(env):
    _setup(env, watchlist=("EURUSD",), market_hours_only=True)
    with env.Session() as db:
        A.start(db)
    saturday = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    assert A.run_tick(now=saturday)["ran"] == []
    assert env.calls == []


def test_decisions_are_parsed(env):
    _setup(env)
    with env.Session() as db:
        A.start(db)
    A.run_tick()
    with env.Session() as db:
        d = A.decisions(db, 5)
    assert d[0]["ticker"] == "BTC-USD" and d[0]["decision"]["action"] == "BUY"


# ── force_confirmation fix ────────────────────────────────────────────

def test_force_confirmation_applies_to_the_graph_that_runs(env, monkeypatch):
    uid = _setup(env)
    engine = NS(require_confirmation=False)
    graph = MagicMock()
    graph.execution_engine = engine
    graph.propagate.side_effect = RuntimeError("stop here")  # we only care about the flag
    import api.dependencies
    monkeypatch.setattr(api.dependencies, "init_graph", lambda config=None: graph)
    from importlib import reload
    import api.tasks as T
    monkeypatch.undo()  # undo the fake _do_analysis from the fixture; keep what's set below
    monkeypatch.setattr(api.dependencies, "init_graph", lambda config=None: graph)
    import api.database
    monkeypatch.setattr(api.database, "SessionLocal", env.Session)
    with env.Session() as db:
        db.add(TaskResult(task_id="t1", user_id=uid, ticker="BTC-USD", status="queued"))
        db.commit()
    T._do_analysis("t1", uid, "BTC-USD", "2026-11-17", True, force_confirmation=True)
    assert engine.require_confirmation is True
    engine.require_confirmation = False
    T._do_analysis("t1", uid, "BTC-USD", "2026-11-17", True)
    assert engine.require_confirmation is False
