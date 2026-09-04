"""Tests for venue-resident protective stop-losses (Blocker 1).

Before this, `stop_loss_pct` from a decision was recorded in memory and
nothing anywhere ever acted on it: no stop order was sent to the exchange,
and the only local monitor (RealtimeFeed) is never started by the API
server. A filled position was therefore completely unprotected.

The contract these tests defend:
  1. A stop actually rests at the venue after a fill.
  2. It fires when price crosses it.
  3. A broker that cannot rest stops must REFUSE loudly — never appear to
     have placed one.
  4. Failure to place a stop is reported as an unprotected position, but
     never unwinds the entry that already filled.
"""

from unittest.mock import MagicMock, patch

import pytest

from tradingagents.execution.brokers.broker_base import BaseBroker
from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.order_models import (
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    TradeAction,
    TradeDecision,
)


@pytest.fixture
def broker():
    b = PaperBroker(initial_cash=100_000.0)
    b.set_price("BTC/USDT", 100_000.0)
    return b


class TestPaperBrokerStops:
    def test_stop_rests_after_registration(self, broker):
        r = broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        assert r.status == OrderStatus.SUBMITTED
        assert r.order_type == OrderType.STOP
        assert len(broker._resting_stops) == 1

    def test_long_stop_fires_when_price_falls_through(self, broker):
        broker.place_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET)
        broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        assert "BTC/USDT" in broker._positions

        broker.set_price("BTC/USDT", 94_000.0)
        assert "BTC/USDT" not in broker._positions, "stop must have closed the position"
        assert not broker._resting_stops, "a fired stop must not stay resting"

    def test_long_stop_does_not_fire_above_the_trigger(self, broker):
        broker.place_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET)
        broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        broker.set_price("BTC/USDT", 96_000.0)
        assert "BTC/USDT" in broker._positions
        assert len(broker._resting_stops) == 1

    def test_stop_fires_exactly_at_the_trigger(self, broker):
        broker.place_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET)
        broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        broker.set_price("BTC/USDT", 95_000.0)
        assert not broker._resting_stops

    def test_short_stop_fires_when_price_rises_through(self, broker):
        broker.place_stop_loss_order("BTC/USDT", OrderSide.BUY, 0.5, 105_000.0)
        broker.set_price("BTC/USDT", 104_000.0)
        assert len(broker._resting_stops) == 1, "must not fire below the trigger"
        broker.set_price("BTC/USDT", 106_000.0)
        assert not broker._resting_stops

    def test_set_prices_bulk_also_triggers(self, broker):
        broker.place_order("BTC/USDT", OrderSide.BUY, 0.5, OrderType.MARKET)
        broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        broker.set_prices({"BTC/USDT": 90_000.0, "ETH/USDT": 3_000.0})
        assert "BTC/USDT" not in broker._positions

    def test_only_the_matching_ticker_fires(self, broker):
        broker.set_price("ETH/USDT", 3_000.0)
        broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        broker.set_price("ETH/USDT", 100.0)   # crashes a DIFFERENT market
        assert len(broker._resting_stops) == 1

    def test_cancel_removes_the_resting_stop(self, broker):
        r = broker.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        assert broker.cancel_stop_loss_order(r.order_id) is True
        assert not broker._resting_stops
        broker.set_price("BTC/USDT", 90_000.0)   # must not fire after cancel

    def test_cancelling_unknown_id_is_false_not_an_error(self, broker):
        assert broker.cancel_stop_loss_order("nope") is False


class TestBaseBrokerContract:
    def test_unsupported_broker_raises_rather_than_pretending(self):
        # Returning a rejected OrderResult would let a caller mistake
        # "unsupported" for "placed"; raising makes it impossible.
        class NoStops(BaseBroker):
            def place_order(self, *a, **k): ...
            def cancel_order(self, *a, **k): ...
            def get_order_status(self, *a, **k): ...
            def get_balance(self): ...
            def get_positions(self): ...
            def get_current_price(self, ticker): ...

        with pytest.raises(NotImplementedError, match="UNPROTECTED"):
            NoStops().place_stop_loss_order("BTC", OrderSide.SELL, 1.0, 100.0)


class TestCcxtStopOrder:
    def _broker(self):
        from tradingagents.execution.brokers.ccxt_broker import CcxtBroker
        import threading
        from tradingagents.execution.retry import RetryConfig

        b = object.__new__(CcxtBroker)
        b.name = "ccxt_test"
        b.exchange_id = "binance"
        b.default_quote = "USDT"
        b.exchange = MagicMock()
        b._entry_price_cache = {}
        b._cache_lock = threading.Lock()
        b._retry_config = RetryConfig(max_retries=0)
        b._db = None
        b.market_type = "spot"
        return b

    def test_sends_a_reduce_only_stop_to_the_venue(self):
        b = self._broker()
        b.exchange.create_order.return_value = {"id": "stop_1", "status": "open"}

        r = b.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)

        assert r.status == OrderStatus.SUBMITTED
        params = b.exchange.create_order.call_args.kwargs["params"]
        # reduce-only is what stops a fired stop from OPENING a new
        # position when the original one is already gone.
        assert params["reduceOnly"] is True
        assert params["stopPrice"] == 95_000.0

    def test_futures_includes_position_side(self):
        b = self._broker()
        b.market_type = "future"
        b.exchange.create_order.return_value = {"id": "stop_1"}
        b.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0, position_side="LONG")
        assert b.exchange.create_order.call_args.kwargs["params"]["positionSide"] == "LONG"

    def test_venue_rejection_is_reported_not_raised(self):
        b = self._broker()
        b.exchange.create_order.side_effect = Exception("stop orders unsupported")
        r = b.place_stop_loss_order("BTC/USDT", OrderSide.SELL, 0.5, 95_000.0)
        assert r.status == OrderStatus.REJECTED
        assert "unsupported" in r.error_message


class TestExecutionEngineWiring:
    """The engine must place the stop itself — a broker that supports stops
    is useless if nothing ever calls it."""

    def _engine(self, broker):
        from tradingagents.execution.execution_engine import ExecutionEngine
        from tradingagents.execution.portfolio_manager import PortfolioManager

        return ExecutionEngine(
            broker=broker,
            portfolio_manager=PortfolioManager(initial_cash=100_000.0),
            require_confirmation=False,
        )

    def _fill(self, ticker="BTC/USDT", qty=0.5, price=100_000.0):
        return OrderResult(
            order_id="entry_1", ticker=ticker, side=OrderSide.BUY,
            order_type=OrderType.MARKET, status=OrderStatus.FILLED,
            requested_quantity=qty, filled_quantity=qty, filled_price=price,
            broker_name="paper",
        )

    def _decision(self, **kw):
        return TradeDecision(
            action=TradeAction.BUY, ticker="BTC/USDT",
            confidence_score=0.9, quantity_pct=0.1, **kw
        )

    def test_places_a_stop_on_the_opposite_side(self, broker):
        eng = self._engine(broker)
        oid = eng._place_protective_stop("BTC/USDT", self._fill(), 95_000.0, self._decision())
        assert oid is not None
        assert broker._resting_stops[oid]["side"] == OrderSide.SELL, "closing side, not entry side"
        assert eng._protective_stops["BTC/USDT"] == oid

    def test_missing_stop_price_is_reported_as_unprotected(self, broker, caplog):
        eng = self._engine(broker)
        with caplog.at_level("CRITICAL"):
            oid = eng._place_protective_stop("BTC/USDT", self._fill(), None, self._decision())
        assert oid is None
        assert "UNPROTECTED" in caplog.text

    def test_broker_without_stop_support_is_reported_not_crashed(self, caplog):
        b = PaperBroker(initial_cash=100_000.0)
        b.place_stop_loss_order = MagicMock(side_effect=NotImplementedError("no stops here"))
        eng = self._engine(b)
        with caplog.at_level("CRITICAL"):
            oid = eng._place_protective_stop("BTC/USDT", self._fill(), 95_000.0, self._decision())
        assert oid is None
        assert "UNPROTECTED" in caplog.text

    def test_venue_rejection_is_reported_as_unprotected(self, caplog):
        b = PaperBroker(initial_cash=100_000.0)
        b.place_stop_loss_order = MagicMock(return_value=OrderResult(
            order_id="x", ticker="BTC/USDT", side=OrderSide.SELL,
            order_type=OrderType.STOP, status=OrderStatus.REJECTED,
            requested_quantity=0.5, error_message="rejected by venue",
            broker_name="paper",
        ))
        eng = self._engine(b)
        with caplog.at_level("CRITICAL"):
            oid = eng._place_protective_stop("BTC/USDT", self._fill(), 95_000.0, self._decision())
        assert oid is None
        assert "UNPROTECTED" in caplog.text

    def test_an_entry_that_filled_is_never_unwound_by_a_stop_failure(self, caplog):
        # The position exists on the venue regardless; raising here would
        # lose track of it entirely.
        b = PaperBroker(initial_cash=100_000.0)
        b.place_stop_loss_order = MagicMock(side_effect=RuntimeError("network died"))
        eng = self._engine(b)
        with caplog.at_level("CRITICAL"):
            assert eng._place_protective_stop("BTC/USDT", self._fill(), 95_000.0, self._decision()) is None

    def test_cancelling_clears_tracking(self, broker):
        eng = self._engine(broker)
        eng._place_protective_stop("BTC/USDT", self._fill(), 95_000.0, self._decision())
        eng._cancel_protective_stop("BTC/USDT")
        assert "BTC/USDT" not in eng._protective_stops
        assert not broker._resting_stops

    def test_cancelling_an_untracked_ticker_is_a_noop(self, broker):
        self._engine(broker)._cancel_protective_stop("NOPE")   # must not raise
