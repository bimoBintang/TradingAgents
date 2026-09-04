"""Alpaca broker for US stock trading.

Supports paper and live trading via the Alpaca Markets API.
Requires the `alpaca-py` package: pip install alpaca-py

Includes market hours enforcement (09:30-16:00 ET, weekdays only).

Usage:
    broker = AlpacaBroker(
        api_key="your_api_key",
        api_secret="your_secret",
        paper=True,  # Use paper trading
    )
"""

import logging
import uuid
from datetime import datetime, time as dtime, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import (
        MarketOrderRequest,
        LimitOrderRequest,
        StopOrderRequest,
        StopLimitOrderRequest,
    )
    from alpaca.trading.enums import (
        OrderSide as AlpacaOrderSide,
        TimeInForce,
        OrderStatus as AlpacaOrderStatus,
    )
    from alpaca.data.live import StockDataStream
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestQuoteRequest
except ImportError:
    raise ImportError(
        "alpaca-py is required for Alpaca broker. Install it: pip install alpaca-py"
    )

from tradingagents.execution.order_models import (
    OrderSide,
    OrderType,
    OrderStatus,
    OrderResult,
    PositionInfo,
)
from .broker_base import BaseBroker


# ── Custom Exceptions ─────────────────────────────────────────────────

class MarketClosedError(Exception):
    """Raised when attempting to submit an order outside US market hours."""

    def __init__(self, current_time_et: str, next_open: str = ""):
        msg = f"US market is closed. Current ET time: {current_time_et}"
        if next_open:
            msg += f". Next open: {next_open}"
        super().__init__(msg)
        self.current_time_et = current_time_et
        self.next_open = next_open


# Map Alpaca statuses to our OrderStatus
_STATUS_MAP = {
    AlpacaOrderStatus.NEW: OrderStatus.SUBMITTED,
    AlpacaOrderStatus.PENDING_NEW: OrderStatus.PENDING,
    AlpacaOrderStatus.ACCEPTED: OrderStatus.SUBMITTED,
    AlpacaOrderStatus.FILLED: OrderStatus.FILLED,
    AlpacaOrderStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
    AlpacaOrderStatus.CANCELED: OrderStatus.CANCELLED,
    AlpacaOrderStatus.EXPIRED: OrderStatus.EXPIRED,
    AlpacaOrderStatus.REJECTED: OrderStatus.REJECTED,
}

# US market hours (ET)
_MARKET_OPEN = dtime(9, 30)   # 09:30 ET
_MARKET_CLOSE = dtime(16, 0)  # 16:00 ET


class AlpacaBroker(BaseBroker):
    """Broker implementation for US stock trading via Alpaca Markets.

    Supports paper trading (free, no real money) and live trading.
    Best for US equities with zero-commission trading.

    Enforces US market hours (09:30-16:00 ET, Mon-Fri).
    Use enforce_market_hours=False to bypass for after-hours testing.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        paper: bool = True,
        enforce_market_hours: bool = True,
        name: str = "alpaca",
    ):
        """Initialize Alpaca broker.

        Args:
            api_key: Alpaca API key
            api_secret: Alpaca API secret
            paper: Use paper trading (True) or live trading (False)
            enforce_market_hours: Reject orders outside US market hours
            name: Broker identifier
        """
        super().__init__(name=f"alpaca_{'paper' if paper else 'live'}")
        self.paper = paper
        self.enforce_market_hours = enforce_market_hours

        # Trading client
        self.client = TradingClient(
            api_key=api_key,
            secret_key=api_secret,
            paper=paper,
        )

        # Data client for price fetching
        self.data_client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=api_secret,
        )

        mode = "PAPER" if paper else "LIVE"
        logger.info("Connected in %s mode (market hours enforcement: %s)", mode, enforce_market_hours)

    # ── Market Hours Check ────────────────────────────────────────────

    @staticmethod
    def _get_eastern_time() -> datetime:
        """Get current time in US Eastern timezone.

        Uses UTC offset calculation (ET = UTC-5, EDT = UTC-4).
        For production, consider pytz or zoneinfo.
        """
        utc_now = datetime.utcnow()
        # Simplified: assume EDT (UTC-4) during March-November,
        # EST (UTC-5) during November-March.
        month = utc_now.month
        if 3 <= month <= 10:
            # EDT (UTC-4)
            return utc_now - timedelta(hours=4)
        else:
            # EST (UTC-5)
            return utc_now - timedelta(hours=5)

    def _check_market_hours(self) -> Optional[str]:
        """Check if current time is within US market hours.

        Returns None if market is open, or an error message string if closed.
        """
        if not self.enforce_market_hours:
            return None

        et_now = self._get_eastern_time()

        # Check weekday (0=Mon, 4=Fri, 5=Sat, 6=Sun)
        if et_now.weekday() >= 5:
            next_mon = et_now + timedelta(days=(7 - et_now.weekday()))
            return (
                f"Market closed (weekend). "
                f"Current ET: {et_now.strftime('%A %H:%M')}. "
                f"Next open: Monday {next_mon.strftime('%Y-%m-%d')} 09:30 ET"
            )

        current_time = et_now.time()
        if current_time < _MARKET_OPEN:
            return (
                f"Market not yet open. "
                f"Current ET: {et_now.strftime('%H:%M')}. "
                f"Opens at 09:30 ET"
            )
        elif current_time >= _MARKET_CLOSE:
            # Next trading day
            next_day = et_now + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            return (
                f"Market closed for the day. "
                f"Current ET: {et_now.strftime('%H:%M')}. "
                f"Next open: {next_day.strftime('%Y-%m-%d')} 09:30 ET"
            )

        return None  # Market is open

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderResult:
        """Place an order via Alpaca.

        Raises MarketClosedError if enforcement is active and market is closed.
        """
        # Market hours check
        market_msg = self._check_market_hours()
        if market_msg:
            et_str = self._get_eastern_time().strftime("%Y-%m-%d %H:%M:%S ET")
            raise MarketClosedError(current_time_et=et_str, next_open=market_msg)

        alpaca_side = AlpacaOrderSide.BUY if side == OrderSide.BUY else AlpacaOrderSide.SELL

        try:
            # Build order request based on type
            if order_type == OrderType.MARKET:
                order_request = MarketOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                )
            elif order_type == OrderType.LIMIT:
                if limit_price is None:
                    raise ValueError("limit_price required for LIMIT orders")
                order_request = LimitOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                )
            elif order_type == OrderType.STOP:
                if stop_price is None:
                    raise ValueError("stop_price required for STOP orders")
                order_request = StopOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    stop_price=stop_price,
                )
            elif order_type == OrderType.STOP_LIMIT:
                if limit_price is None or stop_price is None:
                    raise ValueError("Both limit_price and stop_price required for STOP_LIMIT")
                order_request = StopLimitOrderRequest(
                    symbol=ticker,
                    qty=quantity,
                    side=alpaca_side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=limit_price,
                    stop_price=stop_price,
                )
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

            # Submit order
            order = self.client.submit_order(order_request)
            status = _STATUS_MAP.get(order.status, OrderStatus.SUBMITTED)

            filled_qty = float(order.filled_qty or 0)
            requested_qty = float(order.qty or quantity)
            remaining_qty = max(0.0, requested_qty - filled_qty)

            return OrderResult(
                order_id=str(order.id),
                ticker=ticker,
                side=side,
                order_type=order_type,
                status=status,
                requested_quantity=requested_qty,
                filled_quantity=filled_qty,
                remaining_quantity=remaining_qty,
                requested_price=limit_price,
                filled_price=float(order.filled_avg_price) if order.filled_avg_price else None,
                average_fill_price=float(order.filled_avg_price) if order.filled_avg_price else None,
                broker_name=self.name,
                raw_response={
                    "id": str(order.id),
                    "status": str(order.status),
                    "filled_qty": str(order.filled_qty),
                    "filled_avg_price": str(order.filled_avg_price),
                },
            )

        except MarketClosedError:
            raise  # Re-raise market hours error

        except Exception as e:
            return OrderResult(
                order_id=f"failed_{uuid.uuid4().hex[:8]}",
                ticker=ticker,
                side=side,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                requested_quantity=quantity,
                requested_price=limit_price,
                error_message=f"Alpaca order error: {str(e)}",
                broker_name=self.name,
            )

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Cancel an order via Alpaca (symbol is accepted but not used)."""
        try:
            self.client.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.error("Cancel failed: %s", e)
            return False

    def get_order_status(self, order_id: str) -> OrderResult:
        """Get order status from Alpaca."""
        try:
            order = self.client.get_order_by_id(order_id)
            status = _STATUS_MAP.get(order.status, OrderStatus.PENDING)

            filled_qty = float(order.filled_qty or 0)
            requested_qty = float(order.qty or 0)
            remaining_qty = max(0.0, requested_qty - filled_qty)

            return OrderResult(
                order_id=str(order.id),
                ticker=order.symbol,
                side=OrderSide.BUY if order.side == AlpacaOrderSide.BUY else OrderSide.SELL,
                status=status,
                requested_quantity=requested_qty,
                filled_quantity=filled_qty,
                remaining_quantity=remaining_qty,
                filled_price=float(order.filled_avg_price) if order.filled_avg_price else None,
                average_fill_price=float(order.filled_avg_price) if order.filled_avg_price else None,
                broker_name=self.name,
            )
        except Exception as e:
            return OrderResult(
                order_id=order_id,
                ticker="UNKNOWN",
                side=OrderSide.BUY,
                status=OrderStatus.REJECTED,
                requested_quantity=0,
                error_message=f"Failed to fetch order: {str(e)}",
                broker_name=self.name,
            )

    def get_balance(self) -> Dict[str, float]:
        """Get account balance from Alpaca.

        Swallows all errors and returns a zeroed fallback dict — meant for
        UI display resilience. Must NOT be used to verify credentials; use
        `fetch_balance_strict()` (via `health_check()`) for that.
        """
        try:
            return self._fetch_balance_raw()
        except Exception as e:
            logger.error("Balance fetch failed: %s", e)
            return {"cash": 0.0, "total_equity": 0.0, "buying_power": 0.0}

    def fetch_balance_strict(self) -> Dict[str, float]:
        """Fetch balance WITHOUT the safety net — invalid API key/secret or
        network failures propagate as exceptions. Used by health_check().
        """
        return self._fetch_balance_raw()

    def _fetch_balance_raw(self) -> Dict[str, float]:
        """Shared unguarded balance fetch for get_balance() and fetch_balance_strict()."""
        account = self.client.get_account()
        return {
            "cash": float(account.cash),
            "total_equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "pnl": float(account.equity) - float(account.last_equity),
        }

    def get_positions(self) -> List[PositionInfo]:
        """Get all open positions from Alpaca."""
        positions = []
        try:
            alpaca_positions = self.client.get_all_positions()
            for pos in alpaca_positions:
                side = OrderSide.BUY if float(pos.qty) > 0 else OrderSide.SELL
                positions.append(
                    PositionInfo(
                        ticker=pos.symbol,
                        side=side,
                        quantity=abs(float(pos.qty)),
                        entry_price=float(pos.avg_entry_price),
                        current_price=float(pos.current_price),
                        entry_timestamp=datetime.utcnow(),  # Alpaca doesn't expose exact entry time
                    )
                )
        except Exception as e:
            logger.error("Position fetch failed: %s", e)

        return positions

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get current price via Alpaca data API."""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=ticker)
            quotes = self.data_client.get_stock_latest_quote(request)
            if ticker in quotes:
                quote = quotes[ticker]
                # Use midpoint of bid/ask
                if quote.bid_price and quote.ask_price:
                    return (quote.bid_price + quote.ask_price) / 2
                return quote.ask_price or quote.bid_price
        except Exception as e:
            logger.error("Price fetch failed for %s: %s", ticker, e)
        return None

    def close_all_positions(self) -> List[OrderResult]:
        """Close all positions using Alpaca's API."""
        try:
            self.client.close_all_positions(cancel_orders=True)
            logger.info("All positions closed")
            return []
        except Exception as e:
            logger.error("Close all failed: %s", e)
            # Fallback to parent implementation
            return super().close_all_positions()
