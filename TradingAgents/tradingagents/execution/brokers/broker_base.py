"""Abstract base class for all broker implementations.

All brokers (Paper, CCXT, Alpaca) implement this interface so
the ExecutionEngine can work with any broker interchangeably.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict

from tradingagents.execution.order_models import (
    OrderSide,
    OrderType,
    OrderResult,
    PositionInfo,
)


class BrokerConnectionError(Exception):
    """Raised when a broker is unreachable or fails health check.

    Typically thrown during initialization when the factory
    pings the broker and gets no valid response.
    """

    def __init__(self, broker_name: str, detail: str = ""):
        msg = f"Broker '{broker_name}' is unreachable"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.broker_name = broker_name
        self.detail = detail


class BaseBroker(ABC):
    """Abstract base class for broker implementations.

    Defines the standard interface that all brokers must implement
    for the ExecutionEngine to submit orders and query state.
    """

    def __init__(self, name: str = "base"):
        self.name = name

    @abstractmethod
    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderResult:
        """Submit an order to the broker.

        Args:
            ticker: Asset ticker symbol (e.g., 'NVDA', 'BTC/USDT')
            side: BUY or SELL
            quantity: Number of units to trade
            order_type: MARKET, LIMIT, STOP, or STOP_LIMIT
            limit_price: Price for LIMIT / STOP_LIMIT orders
            stop_price: Trigger price for STOP / STOP_LIMIT orders

        Returns:
            OrderResult with fill details and status
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Cancel a pending order.

        Args:
            order_id: The broker's order ID
            symbol: Trading pair symbol (e.g. 'BTC/USDT'). Required by some
                     CCXT exchanges (Bybit, OKX, Binance Futures). Optional
                     for brokers that can resolve orders by ID alone.

        Returns:
            True if cancellation was successful
        """
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResult:
        """Get the current status of a submitted order.

        Args:
            order_id: The broker's order ID

        Returns:
            Updated OrderResult with current status
        """
        ...

    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """Get account balance.

        Returns:
            Dict with balance info, e.g.:
            {"cash": 10000.0, "total_equity": 12500.0, "buying_power": 9000.0}
        """
        ...

    @abstractmethod
    def get_positions(self) -> List[PositionInfo]:
        """Get all open positions.

        Returns:
            List of PositionInfo objects for each open position
        """
        ...

    @abstractmethod
    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the current market price for an asset.

        Args:
            ticker: Asset ticker symbol

        Returns:
            Current price or None if unavailable
        """
        ...

    def place_stop_loss_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        stop_price: float,
        position_side: Optional[str] = None,
    ) -> OrderResult:
        """Place a protective stop-loss order that rests AT THE VENUE.

        This is the difference between a stop that exists and a stop that
        is merely intended. An exchange-resident stop still fires when this
        process has crashed, the host has lost power, or the network is
        partitioned — precisely the moments a position is most likely to be
        moving against you. A stop tracked only in local memory protects
        nothing in any of those cases.

        Args:
            ticker: Asset to protect.
            side: Side of the CLOSING order (SELL to protect a long,
                BUY to protect a short) — not the side of the entry.
            quantity: Size to close.
            stop_price: Trigger price.
            position_side: Futures hedge mode: "LONG" or "SHORT".

        Returns:
            OrderResult for the resting stop order.

        Raises:
            NotImplementedError: If this broker cannot rest a stop at the
                venue. Deliberately raises instead of returning a rejected
                OrderResult, so a caller cannot mistake "unsupported" for
                "placed and working" — an unprotected position must be an
                explicit, loud condition.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support venue-resident stop-loss orders. "
            "Any position opened through it is UNPROTECTED if this process stops running."
        )

    def get_order_book(self, ticker: str, depth: int = 20) -> Optional[dict]:
        """Fetch Level 2 order book data for a ticker.

        Returns dict with 'bids' and 'asks' lists of [price, volume] pairs,
        or None if not supported by this broker.

        Override in subclasses that support order book data (e.g., CcxtBroker).
        """
        return None

    def fetch_balance_strict(self) -> Dict[str, float]:
        """Fetch balance WITHOUT swallowing errors — used for real connectivity checks.

        `get_balance()` is deliberately resilient for UI display: brokers
        like CcxtBroker/AlpacaBroker catch every exception there (bad
        credentials, network errors, ...) and return a zeroed fallback dict
        so a transient hiccup doesn't crash the dashboard. That resilience
        means `get_balance()` NEVER raises — which makes it useless as a
        connectivity/credentials check: `health_check()` calling it would
        report "healthy" for literally any api_key/api_secret, valid or not.

        Default implementation delegates to get_balance() (fine for brokers
        with no swallow-on-failure behavior, e.g. PaperBroker, which never
        makes network calls). CcxtBroker and AlpacaBroker MUST override this
        with a raw, unguarded fetch so real failures propagate.
        """
        return self.get_balance()

    def health_check(self) -> bool:
        """Verify broker connectivity and basic functionality.

        Attempts an unguarded account balance fetch as a connectivity test —
        see `fetch_balance_strict()` for why this must NOT be `get_balance()`.
        Subclasses may override with more specific checks.

        Returns:
            True if broker is healthy

        Raises:
            BrokerConnectionError: if broker is unreachable or credentials are invalid
        """
        try:
            balance = self.fetch_balance_strict()
            if not isinstance(balance, dict):
                raise BrokerConnectionError(
                    self.name, "balance fetch returned invalid response"
                )
            return True
        except BrokerConnectionError:
            raise
        except Exception as e:
            raise BrokerConnectionError(self.name, str(e)) from e

    def close_all_positions(self) -> List[OrderResult]:
        """Close all open positions (emergency / kill switch).

        Returns:
            List of OrderResults for each close order
        """
        results = []
        positions = self.get_positions()
        for pos in positions:
            # Close by selling if long, buying if short
            close_side = OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY
            result = self.place_order(
                ticker=pos.ticker,
                side=close_side,
                quantity=pos.quantity,
                order_type=OrderType.MARKET,
            )
            results.append(result)
        return results

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name})>"

