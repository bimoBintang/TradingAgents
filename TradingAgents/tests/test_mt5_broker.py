"""MT5Broker against a fake `mt5` module (no Wine/terminal needed)."""

from types import SimpleNamespace as NS

import pytest

from tradingagents.execution.brokers.broker_base import BrokerConnectionError
from tradingagents.execution.brokers.mt5_broker import (
    MT5Broker, canonical_symbol, mt5_env_configured,
)
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.order_models import OrderSide, OrderStatus, OrderType
from tradingagents.execution.portfolio_manager import PortfolioManager


class FakeMT5:
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT, ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 2, 3, 4, 5
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL = 10009, 10010
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    ORDER_STATE_FILLED = 4
    TIMEFRAME_H1 = 16385

    def __init__(self):
        self.sent = []
        self.positions = []
        self.retcode = self.TRADE_RETCODE_DONE
        self.login_ok = True
        self.leverage = 100
        self._next = 1000

    def initialize(self): return True
    def login(self, *a, **k): return self.login_ok
    def last_error(self): return (1, "boom")
    def symbol_select(self, s, on): return True

    def symbol_info(self, s):
        if s != "EURUSD":
            return None
        return NS(trade_contract_size=100000.0, volume_min=0.01, volume_max=100.0,
                  volume_step=0.01, filling_mode=2)

    def symbol_info_tick(self, s): return NS(bid=1.0999, ask=1.1001)

    def positions_get(self, symbol=None, ticket=None):
        ps = self.positions
        if symbol: ps = [p for p in ps if p.symbol == symbol]
        if ticket: ps = [p for p in ps if p.ticket == ticket]
        return ps

    def order_send(self, req):
        self.sent.append(req)
        self._next += 1
        if req["action"] == self.TRADE_ACTION_SLTP:
            for p in self.positions:
                if p.ticket == req["position"]:
                    p.sl = req["sl"]
        return NS(retcode=self.retcode, comment="fake", order=self._next,
                  volume=req.get("volume", 0), price=req.get("price", 0))

    def account_info(self):
        return NS(margin_free=1000.0, leverage=self.leverage, equity=1200.0, balance=1100.0)

    def copy_rates_from_pos(self, s, tf, start, n):
        return [{"high": 1.11 + i * 0.001, "low": 1.10 + i * 0.001, "close": 1.105 + i * 0.001}
                for i in range(n)]


def pos(ticket, ptype, vol=0.10, sl=0.0):
    return NS(ticket=ticket, symbol="EURUSD", type=ptype, volume=vol, price_open=1.10,
              price_current=1.11, sl=sl, tp=0.0, time=1_700_000_000)


@pytest.fixture
def fake():
    return FakeMT5()


@pytest.fixture
def broker(fake):
    return MT5Broker(login=1, password="p", server="s", mt5=fake)


def test_symbol_normalisation():
    assert canonical_symbol("EURUSD=X") == canonical_symbol("EUR/USD") == "EURUSD"
    assert MT5Broker(mt5=FakeMT5(), symbol_suffix=".m")._sym("EUR/USD") == "EURUSD.m"


def test_units_become_lots_rounded_down(broker, fake):
    r = broker.place_order("EURUSD", OrderSide.BUY, 12_990.0)  # 0.1299 lot -> 0.12
    assert r.status == OrderStatus.FILLED
    assert fake.sent[0]["volume"] == pytest.approx(0.12)
    assert r.filled_quantity == pytest.approx(12_000.0)
    assert fake.sent[0]["price"] == 1.1001  # ask for a buy


def test_below_min_lot_is_rejected_not_rounded_up(broker, fake):
    r = broker.place_order("EURUSD", OrderSide.BUY, 500.0)
    assert r.status == OrderStatus.REJECTED and "minimum lot" in r.error_message
    assert not fake.sent


def test_broker_rejection_is_reported(broker, fake):
    fake.retcode = 10006
    r = broker.place_order("EURUSD", OrderSide.BUY, 10_000.0)
    assert r.status == OrderStatus.REJECTED and "10006" in r.error_message


def test_unknown_symbol_rejected(broker):
    assert broker.place_order("XXXYYY", OrderSide.BUY, 10_000.0).status == OrderStatus.REJECTED


def test_sell_against_long_closes_by_ticket(broker, fake):
    fake.positions = [pos(7, fake.POSITION_TYPE_BUY, 0.10)]
    r = broker.place_order("EURUSD", OrderSide.SELL, 10_000.0)
    assert r.status == OrderStatus.FILLED
    assert fake.sent[0]["position"] == 7 and len(fake.sent) == 1


def test_sell_without_position_opens_short(broker, fake):
    broker.place_order("EURUSD", OrderSide.SELL, 10_000.0)
    assert "position" not in fake.sent[0] and fake.sent[0]["type"] == fake.ORDER_TYPE_SELL


def test_stop_lives_on_position_and_can_be_listed_and_cancelled(broker, fake):
    fake.positions = [pos(7, fake.POSITION_TYPE_BUY)]
    r = broker.place_stop_loss_order("EURUSD", OrderSide.SELL, 10_000.0, 1.09)
    assert r.status == OrderStatus.SUBMITTED and r.order_id == "7"
    assert broker.list_protective_stops("EURUSD") == ["7"]
    assert broker.cancel_protective_stops("EURUSD") == 1
    assert broker.list_protective_stops("EURUSD") == []


def test_stop_without_position_is_rejected(broker):
    assert broker.place_stop_loss_order("EURUSD", OrderSide.SELL, 1.0, 1.09).status == OrderStatus.REJECTED


def test_positions_are_netted_and_ticker_unsuffixed(broker, fake):
    fake.positions = [pos(1, fake.POSITION_TYPE_BUY, 0.30), pos(2, fake.POSITION_TYPE_SELL, 0.10)]
    (p,) = broker.get_positions()
    assert p.ticker == "EURUSD" and p.side == OrderSide.BUY
    assert p.quantity == pytest.approx(20_000.0)


def test_balance_is_notional_buying_power(broker):
    b = broker.fetch_balance_strict()
    assert b["cash"] == 100_000.0 and b["total_equity"] == 1200.0


def test_login_failure_raises_connection_error(fake):
    fake.login_ok = False
    with pytest.raises(BrokerConnectionError):
        MT5Broker(login=1, mt5=fake).fetch_balance_strict()


def test_set_leverage_only_within_account_leverage(broker, fake):
    assert broker.set_leverage("EURUSD", 50) is True
    assert broker.set_leverage("EURUSD", 500) is False


def test_atr_from_candles(broker):
    assert broker.fetch_atr("EURUSD", "1h", 14) == pytest.approx(0.01)  # TR = high-low = 0.01 on every fake candle


def test_engine_uses_broker_atr_and_cancels_mt5_stop(broker, fake):
    eng = ExecutionEngine(broker=broker, portfolio_manager=PortfolioManager(initial_cash=100_000.0),
                          require_confirmation=False)
    assert eng._get_atr("EURUSD") == pytest.approx(broker.fetch_atr("EURUSD"))
    fake.positions = [pos(7, fake.POSITION_TYPE_BUY, sl=1.09)]
    eng._cancel_protective_stop("EURUSD")  # fresh engine: falls back to venue lookup
    assert fake.positions[0].sl == 0.0


def test_env_configured(monkeypatch):
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.delenv(k, raising=False)
    assert not mt5_env_configured()
    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.setenv(k, "1")
    assert mt5_env_configured()


def _user_config_with(monkeypatch, env_on):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from api.models import Base, UserConfig
    from api.user_context import get_user_config

    for k in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        if env_on:
            monkeypatch.setenv(k, "1")
        else:
            monkeypatch.delenv(k, raising=False)
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as db:
        db.add(UserConfig(user_id=1, config_json=json.dumps({"execution": {"broker": "mt5"}})))
        db.commit()
        return get_user_config(db, 1)["execution"]


def test_mt5_not_forced_to_paper_when_env_set(monkeypatch):
    ex = _user_config_with(monkeypatch, True)
    assert ex["broker"] == "mt5" and ex["mode"] == "live"


def test_mt5_forced_to_paper_without_env(monkeypatch):
    ex = _user_config_with(monkeypatch, False)
    assert ex["broker"] == "paper" and ex["mode"] == "paper"
