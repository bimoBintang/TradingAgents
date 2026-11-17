"""MetaTrader 5 broker (forex) over an RPyC bridge to a Wine-hosted terminal.

The official `MetaTrader5` Python package only runs on Windows. Under Wine we run
the terminal plus an `mt5linux` RPyC server inside Wine; this broker talks to it
with the `mt5linux` client, which mimics the `MetaTrader5` module API.

    Linux Python ──rpyc──> mt5linux server (Windows Python in Wine) ──> terminal64.exe

Single account only: one terminal logs into one account, taken from the env
(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER; optional MT5_RPYC_HOST/PORT, MT5_SYMBOL_SUFFIX).

Sizing note: the engine thinks in units; MT5 trades in lots. Units are converted
with the symbol's contract size and rounded DOWN to the volume step. Anything
below the minimum lot is rejected, never rounded up (that would raise the risk).
"""

import logging
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from tradingagents.execution.order_models import (
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionInfo,
    PositionSide,
)
from .broker_base import BaseBroker, BrokerConnectionError

logger = logging.getLogger(__name__)

_REQUIRED_ENV = ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER")

# MT5 timeframe constant names by the strings the engine uses.
_TIMEFRAMES = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1",
}


def mt5_env_configured() -> bool:
    """True when the single MT5 account is fully described by the environment."""
    return all(os.getenv(k) for k in _REQUIRED_ENV)


def canonical_symbol(ticker: str) -> str:
    """'EUR/USD', 'EURUSD=X', 'eurusd' -> 'EURUSD'."""
    t = ticker.upper().replace("=X", "").replace("/", "").replace("-", "").replace("_", "")
    return t


class MT5Broker(BaseBroker):
    """Forex broker for a MetaTrader 5 terminal. Behaves like a futures venue
    (shorting allowed, leverage is account-level)."""

    market_type = "future"

    def __init__(
        self,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        symbol_suffix: Optional[str] = None,
        deviation: int = 20,
        magic: int = 20260101,
        mt5: Any = None,
        name: str = "mt5",
    ):
        super().__init__(name=name)
        self.login = int(login if login is not None else os.getenv("MT5_LOGIN", "0") or 0)
        self.password = password if password is not None else os.getenv("MT5_PASSWORD", "")
        self.server = server if server is not None else os.getenv("MT5_SERVER", "")
        self.host = host or os.getenv("MT5_RPYC_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("MT5_RPYC_PORT", "18812"))
        self.suffix = symbol_suffix if symbol_suffix is not None else os.getenv("MT5_SYMBOL_SUFFIX", "")
        self.deviation = deviation
        self.magic = magic
        self._mt5 = mt5
        self._connected = False

    # ── Connection ────────────────────────────────────────────────────

    def _api(self):
        if self._mt5 is None:
            try:
                from mt5linux import MetaTrader5
            except ImportError as e:
                raise ImportError(
                    "Broker 'mt5' needs the mt5linux client. Install: pip install tradingagents[forex]"
                ) from e
            self._mt5 = MetaTrader5(host=self.host, port=self.port)
        return self._mt5

    def _connect(self):
        mt5 = self._api()
        if self._connected:
            return mt5
        try:
            ok = mt5.initialize()
        except Exception as e:  # rpyc connection refused, bridge down, ...
            raise BrokerConnectionError(self.name, f"cannot reach MT5 bridge {self.host}:{self.port}: {e}") from e
        if not ok:
            raise BrokerConnectionError(self.name, f"initialize() failed: {mt5.last_error()}")
        if not mt5.login(self.login, password=self.password, server=self.server):
            raise BrokerConnectionError(self.name, f"login failed: {mt5.last_error()}")
        self._connected = True
        return mt5

    # ── Symbols / lots ────────────────────────────────────────────────

    def _sym(self, ticker: str) -> str:
        s = canonical_symbol(ticker)
        return s if (self.suffix and s.endswith(self.suffix.upper())) else s + self.suffix

    def _strip(self, symbol: str) -> str:
        return symbol[: -len(self.suffix)] if self.suffix and symbol.endswith(self.suffix) else symbol

    def _info(self, mt5, symbol: str):
        info = mt5.symbol_info(symbol)
        if info is None and mt5.symbol_select(symbol, True):
            info = mt5.symbol_info(symbol)
        return info

    @staticmethod
    def _to_lots(info, quantity: float) -> Optional[float]:
        step = info.volume_step or 0.01
        lots = math.floor(quantity / info.trade_contract_size / step + 1e-9) * step
        lots = round(min(lots, info.volume_max), 8)
        return lots if lots >= info.volume_min else None

    @staticmethod
    def _filling(mt5, info):
        mode = getattr(info, "filling_mode", 0) or 0
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _reject(self, ticker, side, order_type, quantity, msg) -> OrderResult:
        return OrderResult(
            order_id=f"rejected_{int(datetime.utcnow().timestamp() * 1000)}",
            ticker=ticker, side=side, order_type=order_type,
            status=OrderStatus.REJECTED, requested_quantity=max(quantity, 0.0),
            error_message=msg, broker_name=self.name,
        )

    # ── Orders ────────────────────────────────────────────────────────

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        **_ignored,  # engine passes position_side; MT5 positions are tied to the account mode
    ) -> OrderResult:
        try:
            mt5 = self._connect()
            symbol = self._sym(ticker)
            info = self._info(mt5, symbol)
            if info is None:
                return self._reject(ticker, side, order_type, quantity, f"Unknown symbol {symbol}")
            lots = self._to_lots(info, quantity)
            if lots is None:
                return self._reject(
                    ticker, side, order_type, quantity,
                    f"{quantity:g} units is below the minimum lot ({info.volume_min} lot = "
                    f"{info.volume_min * info.trade_contract_size:g} units) for {symbol}",
                )
            buy = side == OrderSide.BUY
            contract = info.trade_contract_size

            if order_type == OrderType.MARKET:
                return self._market(mt5, ticker, symbol, info, buy, lots, contract, side)

            if order_type == OrderType.LIMIT and limit_price:
                otype = mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT
                price = limit_price
            elif order_type == OrderType.STOP and stop_price:
                otype = mt5.ORDER_TYPE_BUY_STOP if buy else mt5.ORDER_TYPE_SELL_STOP
                price = stop_price
            else:
                return self._reject(ticker, side, order_type, quantity, f"Unsupported order type {order_type}")
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_PENDING, "symbol": symbol, "volume": lots,
                "type": otype, "price": price, "deviation": self.deviation, "magic": self.magic,
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN,
            })
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                return self._reject(ticker, side, order_type, quantity, self._why(mt5, res))
            return OrderResult(
                order_id=str(res.order), ticker=ticker, side=side, order_type=order_type,
                status=OrderStatus.SUBMITTED, requested_quantity=quantity,
                requested_price=price, broker_name=self.name,
            )
        except BrokerConnectionError as e:
            return self._reject(ticker, side, order_type, quantity, str(e))
        except Exception as e:
            logger.error("[MT5Broker] place_order failed: %s", e)
            return self._reject(ticker, side, order_type, quantity, f"Unexpected error: {e}")

    def _market(self, mt5, ticker, symbol, info, buy, lots, contract, side) -> OrderResult:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return self._reject(ticker, side, OrderType.MARKET, lots * contract, f"No tick for {symbol}")
        price = tick.ask if buy else tick.bid
        otype = mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL
        opposite_type = mt5.POSITION_TYPE_SELL if buy else mt5.POSITION_TYPE_BUY

        # Close opposing positions by ticket first: on a hedging account a bare
        # opposite order would OPEN a new position instead of closing.
        legs: List[Optional[float]] = []  # volume per leg; ticket None = fresh position
        remaining = lots
        for p in (mt5.positions_get(symbol=symbol) or []):
            if p.type == opposite_type and remaining > 0:
                v = min(p.volume, remaining)
                legs.append((p.ticket, v))
                remaining = round(remaining - v, 8)
        if remaining >= info.volume_min:
            legs.append((None, remaining))

        filled_vol, notional, last_order, err = 0.0, 0.0, "", None
        for ticket, vol in legs:
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": vol, "type": otype,
                "price": price, "deviation": self.deviation, "magic": self.magic,
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(mt5, info),
            }
            if ticket is not None:
                req["position"] = ticket
            res = mt5.order_send(req)
            if res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE, getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", -1)):
                filled_vol += res.volume
                notional += res.volume * (res.price or price)
                last_order = str(res.order)
            else:
                err = self._why(mt5, res)
                break

        if filled_vol <= 0:
            return self._reject(ticker, side, OrderType.MARKET, lots * contract, err or "no fill")
        requested = lots * contract
        filled_units = filled_vol * contract
        full = filled_vol >= lots - 1e-9
        avg = notional / filled_vol
        return OrderResult(
            order_id=last_order, ticker=ticker, side=side, order_type=OrderType.MARKET,
            status=OrderStatus.FILLED if full else OrderStatus.PARTIALLY_FILLED,
            requested_quantity=requested, filled_quantity=filled_units,
            remaining_quantity=max(requested - filled_units, 0.0),
            filled_price=avg, average_fill_price=avg, broker_name=self.name,
            error_message=err,
        )

    @staticmethod
    def _why(mt5, res) -> str:
        if res is None:
            return f"order_send returned None: {mt5.last_error()}"
        return f"retcode {res.retcode}: {getattr(res, 'comment', '')}"

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        try:
            mt5 = self._connect()
            res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(order_id)})
            return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error("[MT5Broker] cancel_order(%s) failed: %s", order_id, e)
            return False

    def get_order_status(self, order_id: str) -> OrderResult:
        base = dict(order_id=str(order_id), ticker="UNKNOWN", side=OrderSide.BUY,
                    requested_quantity=0.0, broker_name=self.name)
        try:
            mt5 = self._connect()
            if mt5.orders_get(ticket=int(order_id)):
                return OrderResult(status=OrderStatus.SUBMITTED, **base)
            hist = mt5.history_orders_get(ticket=int(order_id))
            if hist:
                filled = hist[0].state == mt5.ORDER_STATE_FILLED
                return OrderResult(status=OrderStatus.FILLED if filled else OrderStatus.CANCELLED, **base)
            return OrderResult(status=OrderStatus.REJECTED, error_message="order not found", **base)
        except Exception as e:
            return OrderResult(status=OrderStatus.REJECTED, error_message=str(e), **base)

    # ── Protective stops (SL on the position itself, resting at the broker) ──

    def _positions_for(self, mt5, ticker: str):
        return list(mt5.positions_get(symbol=self._sym(ticker)) or [])

    def _set_sl(self, mt5, position, sl: float) -> bool:
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP, "symbol": position.symbol,
            "position": position.ticket, "sl": sl, "tp": position.tp,
        })
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def place_stop_loss_order(self, ticker, side, quantity, stop_price, position_side=None) -> OrderResult:
        """Attach the SL to the open position(s). No separate pending order exists,
        so there is nothing to orphan when the position closes."""
        try:
            mt5 = self._connect()
            protects = mt5.POSITION_TYPE_BUY if side == OrderSide.SELL else mt5.POSITION_TYPE_SELL
            targets = [p for p in self._positions_for(mt5, ticker) if p.type == protects]
            if not targets:
                return self._reject(ticker, side, OrderType.STOP, quantity, "no open position to protect")
            failed = [p.ticket for p in targets if not self._set_sl(mt5, p, stop_price)]
            if failed:
                return self._reject(ticker, side, OrderType.STOP, quantity, f"SL rejected for ticket(s) {failed}")
            return OrderResult(
                order_id=str(targets[0].ticket), ticker=ticker, side=side, order_type=OrderType.STOP,
                status=OrderStatus.SUBMITTED, requested_quantity=quantity,
                requested_price=stop_price, broker_name=self.name,
            )
        except Exception as e:
            return self._reject(ticker, side, OrderType.STOP, quantity, f"Stop-loss placement failed: {e}")

    def list_protective_stops(self, ticker: str) -> List[str]:
        try:
            return [str(p.ticket) for p in self._positions_for(self._connect(), ticker) if p.sl]
        except Exception as e:
            logger.warning("[MT5Broker] list_protective_stops(%s) failed: %s", ticker, e)
            return []

    def cancel_protective_stops(self, ticker: str) -> int:
        try:
            mt5 = self._connect()
            return sum(1 for p in self._positions_for(mt5, ticker) if p.sl and self._set_sl(mt5, p, 0.0))
        except Exception as e:
            logger.warning("[MT5Broker] cancel_protective_stops(%s) failed: %s", ticker, e)
            return 0

    def cancel_stop_loss_order(self, order_id: str) -> bool:
        """order_id is the position ticket returned by place_stop_loss_order."""
        try:
            mt5 = self._connect()
            for p in (mt5.positions_get(ticket=int(order_id)) or []):
                return self._set_sl(mt5, p, 0.0)
            return False  # position already closed: its SL went with it
        except Exception as e:
            logger.warning("[MT5Broker] cancel_stop_loss_order(%s) failed: %s", order_id, e)
            return False

    # ── Account state ─────────────────────────────────────────────────

    def fetch_balance_strict(self) -> Dict[str, float]:
        mt5 = self._connect()
        acc = mt5.account_info()
        if acc is None:
            raise BrokerConnectionError(self.name, f"account_info() failed: {mt5.last_error()}")
        # Local accounting books full notional per position, so "cash" is notional
        # buying power (free margin x account leverage), not the account balance.
        buying_power = acc.margin_free * (acc.leverage or 1)
        return {
            "cash": float(buying_power), "buying_power": float(buying_power),
            "total_equity": float(acc.equity), "balance": float(acc.balance),
        }

    def get_balance(self) -> Dict[str, float]:
        try:
            return self.fetch_balance_strict()
        except Exception as e:
            logger.error("[MT5Broker] get_balance failed: %s", e)
            return {"cash": 0.0, "buying_power": 0.0, "total_equity": 0.0, "balance": 0.0}

    def get_positions(self) -> List[PositionInfo]:
        """One net position per symbol.

        shortcut: a hedging account holding both directions on one symbol is
        reported net; per-ticket accounting needs the engine keyed by ticket.
        """
        try:
            mt5 = self._connect()
            by_symbol: Dict[str, list] = {}
            for p in (mt5.positions_get() or []):
                by_symbol.setdefault(p.symbol, []).append(p)
            out: List[PositionInfo] = []
            for symbol, ps in by_symbol.items():
                info = self._info(mt5, symbol)
                contract = info.trade_contract_size if info else 1.0
                signed = sum(p.volume if p.type == mt5.POSITION_TYPE_BUY else -p.volume for p in ps)
                if abs(signed) < 1e-9:
                    continue
                buy = signed > 0
                dom = [p for p in ps if (p.type == mt5.POSITION_TYPE_BUY) == buy]
                vol = sum(p.volume for p in dom)
                entry = sum(p.price_open * p.volume for p in dom) / vol
                cur = sum(p.price_current * p.volume for p in dom) / vol
                sls = [p.sl for p in dom if p.sl]
                out.append(PositionInfo(
                    ticker=self._strip(symbol),
                    side=OrderSide.BUY if buy else OrderSide.SELL,
                    quantity=abs(signed) * contract,
                    entry_price=entry, current_price=cur,
                    entry_timestamp=datetime.utcfromtimestamp(min(p.time for p in dom)),
                    stop_loss_price=min(sls) if sls and buy else (max(sls) if sls else None),
                    position_side=PositionSide.LONG if buy else PositionSide.SHORT,
                ))
            return out
        except BrokerConnectionError:
            raise
        except Exception as e:
            logger.error("[MT5Broker] get_positions failed: %s", e)
            return []

    get_futures_positions = get_positions

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            tick = self._connect().symbol_info_tick(self._sym(ticker))
            return (tick.bid + tick.ask) / 2 if tick else None
        except Exception:
            return None

    # ── Engine hooks ──────────────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Leverage is account-level in MT5. Succeeds only if the account already
        allows at least the requested multiple (we cannot change it per order)."""
        try:
            acc = self._connect().account_info()
            return bool(acc) and leverage <= (acc.leverage or 1)
        except Exception:
            return False

    def set_margin_mode(self, symbol: str, margin_type: str = "isolated") -> bool:
        return True  # margin mode is a property of the account, not the order

    def fetch_atr(self, ticker: str, timeframe: str = "1h", period: int = 14) -> Optional[float]:
        try:
            mt5 = self._connect()
            tf = getattr(mt5, _TIMEFRAMES.get(timeframe, "TIMEFRAME_H1"))
            rates = mt5.copy_rates_from_pos(self._sym(ticker), tf, 0, period + 1)
            if rates is None or len(rates) < period + 1:
                return None
            trs = []
            for prev, cur in zip(rates[:-1], rates[1:]):
                h, l, pc = float(cur["high"]), float(cur["low"]), float(prev["close"])
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            return sum(trs[-period:]) / period
        except Exception as e:
            logger.warning("[MT5Broker] fetch_atr(%s) failed: %s", ticker, e)
            return None
