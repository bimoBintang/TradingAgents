"""End-to-end tests for the manual-approval flow (Blockers 3 and 4).

Two defects, which had to be fixed together:

  Blocker 3 — the flow was broken end to end. Nothing ever wrote a
  PendingOrder row; the engine's queue lived in memory on a per-user graph
  that was discarded the moment the analysis finished; and the approve
  endpoint looked in the SHARED singleton graph, which never held the
  order. Since require_confirmation defaults to True, no trade could ever
  execute — and the database was marked APPROVED anyway.

  Blocker 4 — approve_pending_order() went straight from the queue to
  broker.place_order(), skipping the kill switch, RiskController,
  order-flow guard, leverage setup and protective stop, and sizing off a
  price captured at decision time.

Fixing 3 alone would have been worse than leaving both: it would have
switched on an execution path with no guards at all.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from api.database import SessionLocal
from api.models import PendingOrder, User
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.order_models import (
    OrderResult, OrderSide, OrderStatus, OrderType, TradeAction, TradeDecision,
)
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.risk_controls import RiskController


DECISION_JSON = json.dumps({
    "action": "BUY", "ticker": "BTC/USDT", "confidence_score": 0.9,
    "quantity_pct": 0.05, "stop_loss_pct": 0.05, "take_profit_pct": 0.10,
})


def make_engine(require_confirmation=True, risk_controller=None, cash=100_000.0):
    broker = PaperBroker(initial_cash=cash)
    broker.set_price("BTC/USDT", 100_000.0)
    engine = ExecutionEngine(
        broker=broker,
        portfolio_manager=PortfolioManager(initial_cash=cash, max_position_pct=0.10),
        risk_controller=risk_controller,
        require_confirmation=require_confirmation,
    )
    return engine, broker


class TestQueueingStillWorks:
    def test_decision_is_queued_not_executed(self):
        engine, broker = make_engine(require_confirmation=True)
        result = engine.execute_decision(DECISION_JSON)
        assert result is None, "must not execute while awaiting approval"
        assert len(engine.get_pending_orders()) == 1
        assert "BTC/USDT" not in broker._positions

    def test_queued_order_carries_the_decision_payload(self):
        # Without this the approval path has nothing to re-validate.
        engine, _ = make_engine()
        engine.execute_decision(DECISION_JSON)
        assert engine.get_pending_orders()[0]["decision_json"] == DECISION_JSON


class TestApprovalRevalidates:
    """Blocker 4: approval authorizes intent, not skipping the checks."""

    def _queued(self, **kw):
        engine, broker = make_engine(**kw)
        engine.execute_decision(DECISION_JSON)
        key = engine.get_pending_orders()[0]["idempotency_key"]
        return engine, broker, key

    def test_approval_executes_the_trade(self):
        engine, broker, key = self._queued()
        result = engine.execute_approved_order(DECISION_JSON, key)
        assert result is not None
        assert result.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        assert "BTC/USDT" in broker._positions

    def test_kill_switch_tripped_after_queueing_blocks_execution(self):
        rc = RiskController()
        engine, broker, key = self._queued(risk_controller=rc)

        rc.activate_kill_switch("Daily loss limit breached after the decision")

        assert engine.execute_approved_order(DECISION_JSON, key) is None
        assert "BTC/USDT" not in broker._positions, "kill switch must stop an approved order"

    def test_quantity_is_recomputed_from_a_fresh_price(self):
        # The old path multiplied by the price captured at decision time.
        engine, broker, key = self._queued()
        queued_qty = engine.get_pending_orders()[0]["quantity"]

        broker.set_price("BTC/USDT", 50_000.0)   # market halved before approval
        result = engine.execute_approved_order(DECISION_JSON, key)

        assert result is not None
        assert result.filled_quantity > queued_qty * 1.5, (
            "quantity must be recomputed at the new price, not carried over"
        )

    def test_protective_stop_is_placed_on_approval(self):
        # Blocker 1's stop must also cover the approval path.
        engine, broker, key = self._queued()
        engine.execute_approved_order(DECISION_JSON, key)
        assert engine._protective_stops.get("BTC/USDT")
        assert broker._resting_stops

    def test_approved_order_is_not_executable_twice(self):
        engine, broker, key = self._queued()
        first = engine.execute_approved_order(DECISION_JSON, key)
        second = engine.execute_approved_order(DECISION_JSON, key)
        assert first is not None
        assert second is None, "idempotency key must block a repeat approval"

    def test_bypass_only_skips_the_queue_step(self):
        # A direct call with bypass must behave exactly like auto-execute.
        engine, broker = make_engine(require_confirmation=True)
        result = engine.execute_decision(DECISION_JSON, bypass_confirmation=True)
        assert result is not None
        assert not engine.get_pending_orders(), "must not queue when bypassing"

    def test_legacy_approve_without_in_memory_order_returns_none(self):
        engine, _ = make_engine()
        assert engine.approve_pending_order("never-queued") is None


class TestPersistenceAndScoping:
    """Blocker 3: the order must outlive the graph and belong to one user."""

    @pytest.fixture
    def db(self):
        s = SessionLocal()
        yield s
        s.close()

    @pytest.fixture
    def user(self, db):
        u = User(
            email=f"__test_pending_{uuid.uuid4().hex[:10]}__@example.com",
            name="t", hashed_password="x",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        yield u
        try:
            db.query(PendingOrder).filter(PendingOrder.user_id == u.id).delete()
            db.query(User).filter(User.id == u.id).delete()
            db.commit()
        except Exception:
            db.rollback()

    def test_queued_orders_are_written_to_the_database(self, db, user):
        from api.tasks import _persist_pending_orders

        engine, _ = make_engine()
        engine.execute_decision(DECISION_JSON)
        graph = MagicMock()
        graph.execution_engine = engine

        written = _persist_pending_orders(db, user.id, "task-1", graph, {})
        assert written == 1

        row = db.query(PendingOrder).filter(PendingOrder.user_id == user.id).one()
        assert row.status == "PENDING"
        assert row.decision_json == DECISION_JSON
        assert row.expires_at is not None, "an order with no expiry can never go stale"

    def test_persisting_is_idempotent(self, db, user):
        from api.tasks import _persist_pending_orders

        engine, _ = make_engine()
        engine.execute_decision(DECISION_JSON)
        graph = MagicMock()
        graph.execution_engine = engine

        assert _persist_pending_orders(db, user.id, "task-1", graph, {}) == 1
        assert _persist_pending_orders(db, user.id, "task-1", graph, {}) == 0

    def test_ttl_comes_from_config(self, db, user):
        from api.tasks import _persist_pending_orders

        engine, _ = make_engine()
        engine.execute_decision(DECISION_JSON)
        graph = MagicMock()
        graph.execution_engine = engine

        _persist_pending_orders(
            db, user.id, "task-1", graph,
            {"execution": {"pending_order_ttl_seconds": 60}},
        )
        row = db.query(PendingOrder).filter(PendingOrder.user_id == user.id).one()
        created = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
        expires = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
        assert 55 <= (expires - created).total_seconds() <= 65

    def test_orders_are_scoped_to_their_user(self, db, user):
        from api.tasks import _persist_pending_orders

        engine, _ = make_engine()
        engine.execute_decision(DECISION_JSON)
        graph = MagicMock()
        graph.execution_engine = engine
        _persist_pending_orders(db, user.id, "task-1", graph, {})

        other = db.query(PendingOrder).filter(PendingOrder.user_id == user.id + 99_999).all()
        assert other == [], "another user must never see this order"

    def test_engine_without_execution_engine_is_safe(self, db, user):
        from api.tasks import _persist_pending_orders

        graph = MagicMock()
        graph.execution_engine = None
        assert _persist_pending_orders(db, user.id, "t", graph, {}) == 0


class TestExpiry:
    def test_expired_order_is_detectable(self):
        now = datetime.now(timezone.utc)
        row = PendingOrder(
            user_id=1, ticker="BTC/USDT", action="BUY", quantity=1.0, price=1.0,
            value=1.0, confidence=0.9, decision_json=DECISION_JSON,
            idempotency_key="k", status="PENDING",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
        expires = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
        assert now > expires, "a 2-hour-old order must read as expired"
