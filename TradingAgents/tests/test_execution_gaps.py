"""Regression tests for the execution-flow gaps (orphan stops, short handling,
idempotency, reconcile bookkeeping)."""

from unittest.mock import MagicMock

import pytest

from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.order_models import (
    OrderResult, OrderSide, OrderStatus, OrderType, TradeAction, TradeDecision,
)
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.stop_loss_manager import StopLossManager

T = "BTC/USDT"


@pytest.fixture
def broker():
    b = PaperBroker(initial_cash=100_000.0)
    b.set_price(T, 100_000.0)
    return b


def engine(broker, **kw):
    return ExecutionEngine(
        broker=broker,
        portfolio_manager=PortfolioManager(initial_cash=100_000.0),
        require_confirmation=False,
        **kw,
    )


def fill(side, qty=0.5, price=100_000.0):
    return OrderResult(
        order_id="o1", ticker=T, side=side, order_type=OrderType.MARKET,
        status=OrderStatus.FILLED, requested_quantity=qty, filled_quantity=qty,
        filled_price=price, broker_name="paper",
    )


def decision(action=TradeAction.BUY, **kw):
    return TradeDecision(action=action, ticker=T, confidence_score=0.9, quantity_pct=0.1, **kw)


# #1 / #4 -----------------------------------------------------------------
def test_new_engine_cancels_orphan_stop_via_venue(broker):
    broker.place_stop_loss_order(T, OrderSide.SELL, 0.5, 95_000.0)
    eng = engine(broker)  # fresh engine: _protective_stops is empty
    eng._cancel_protective_stop(T)
    assert not broker._resting_stops


def test_software_exit_cancels_venue_stop(broker):
    eng = engine(broker, stop_loss_manager=StopLossManager(trailing_stop_pct=0.05))
    broker.place_order(T, OrderSide.BUY, 0.5, OrderType.MARKET)
    eng.portfolio.open_position(T, OrderSide.BUY, 0.5, 100_000.0)
    eng.stop_loss_manager.register_position(eng.portfolio.positions[T])
    eng._place_protective_stop(T, fill(OrderSide.BUY), 50_000.0, decision())
    assert broker._resting_stops
    eng.process_exit_signals(current_prices={T: 90_000.0})  # below 5% trailing
    assert T not in eng.portfolio.positions
    assert not broker._resting_stops


# #5 ----------------------------------------------------------------------
def test_same_decision_json_gets_same_key(broker):
    d = decision()
    j = '{"x": 1}'
    assert ExecutionEngine._generate_idempotency_key(d, j) == ExecutionEngine._generate_idempotency_key(d, j)
    assert ExecutionEngine._generate_idempotency_key(d, j) != ExecutionEngine._generate_idempotency_key(d, '{"x": 2}')


# #6 ----------------------------------------------------------------------
def test_sell_without_position_rejected_on_spot(broker):
    eng = engine(broker)
    assert "spot" in eng._pre_flight_checks(decision(TradeAction.SELL))


def test_sell_without_position_allowed_on_futures(broker):
    broker.market_type = "future"
    assert engine(broker)._pre_flight_checks(decision(TradeAction.SELL)) is None


def test_short_open_then_cover_books_correct_cash(broker):
    broker.market_type = "future"
    eng = engine(broker)
    eng._handle_fill(decision(TradeAction.SELL, stop_loss_pct=0.05), fill(OrderSide.SELL), 100_000.0)
    assert eng.portfolio.positions[T].side == OrderSide.SELL
    assert broker._resting_stops, "short must get a protective stop"
    cash_open = eng.portfolio.cash_balance
    eng._handle_fill(decision(TradeAction.BUY), fill(OrderSide.BUY, price=90_000.0), 90_000.0)
    assert T not in eng.portfolio.positions
    # short from 100k to 90k on 0.5 = +5k; cash back = cost basis 50k + 5k
    assert eng.portfolio.cash_balance == pytest.approx(cash_open + 55_000.0)


# #3 / #7 -----------------------------------------------------------------
def test_reconcile_books_vanished_position_into_risk_controller(broker):
    rc = MagicMock()
    eng = engine(broker, risk_controller=rc)
    eng.portfolio.open_position(T, OrderSide.BUY, 0.5, 100_000.0)
    eng.portfolio.positions[T].current_price = 90_000.0
    eng.reconcile()  # exchange has no position
    rc.record_trade_result.assert_called_once()
    assert rc.record_trade_result.call_args[0][0] == pytest.approx(-5_000.0)


def test_reconcile_adopted_position_unprotected_is_flagged_and_tracked(broker, caplog):
    slm = StopLossManager()
    eng = engine(broker, stop_loss_manager=slm)
    broker.place_order(T, OrderSide.BUY, 0.5, OrderType.MARKET)
    with caplog.at_level("CRITICAL"):
        eng.reconcile()
    assert T in slm._positions
    assert "UNPROTECTED" in caplog.text
