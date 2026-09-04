"""Paper broker for risk-free simulation trading.

Simulates order execution locally without connecting to any exchange.
Useful for testing strategies, developing new features, and backtesting.
Uses volume-based slippage model for more realistic simulation.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from tradingagents.execution.order_models import (
    OrderSide,
    OrderType,
    OrderStatus,
    OrderResult,
    PositionInfo,
)
from .broker_base import BaseBroker

logger = logging.getLogger(__name__)


class PaperBroker(BaseBroker):
    """Local simulation broker — no real money involved.

    Maintains an in-memory portfolio with configurable initial balance.
    Orders are "filled" instantly at the specified or simulated price.

    Slippage model: volume-based, not flat percentage.
    Formula: slippage = min(base_slippage * (order_value_usd / 10_000), max_slippage)
    Small orders get tiny slippage; large orders get increasingly worse fills.
    """

    def __init__(
        self,
        initial_cash: float = 10000.0,
        commission_pct: float = 0.001,  # 0.1% per trade
        slippage_pct: float = 0.0005,   # Base slippage (scaled by order size)
        max_slippage_pct: float = 0.03,  # Cap at 3% slippage
        name: str = "paper",
    ):
        """Initialize the paper broker.

        Args:
            initial_cash: Starting cash balance
            commission_pct: Commission as percentage of trade value (0.001 = 0.1%)
            slippage_pct: Base slippage percentage, scaled by order value
            max_slippage_pct: Maximum slippage cap (0.03 = 3%)
            name: Broker identifier
        """
        super().__init__(name=name)
        self.initial_cash = initial_cash
        self.cash_balance = initial_cash
        self.commission_pct = commission_pct
        self.base_slippage_pct = slippage_pct
        self.max_slippage_pct = max_slippage_pct

        # Positions: ticker -> {side, quantity, entry_price, entry_time}
        self._positions: Dict[str, dict] = {}

        # Order history
        self._orders: Dict[str, OrderResult] = {}

        # Simulated prices (can be updated externally)
        self._prices: Dict[str, float] = {}

        # Resting protective stops: order_id -> {ticker, side, quantity, stop_price}
        self._resting_stops: Dict[str, dict] = {}

        print(f"[PaperBroker] Initialized with ${initial_cash:,.2f} cash (volume-based slippage)")

    def _calculate_slippage(self, order_value_usd: float) -> float:
        """Calculate slippage using volume-based model.

        Formula: slippage = min(base_slippage * (order_value / 10_000), max_slippage)

        Rationale: larger orders move the market more (market impact).
        A $1,000 order with base 0.05% → 0.005% slippage
        A $10,000 order with base 0.05% → 0.05% slippage
        A $100,000 order with base 0.05% → 0.5% slippage (but capped at max)

        Args:
            order_value_usd: Total order value in USD

        Returns:
            Slippage as a fraction (e.g., 0.001 = 0.1%)
        """
        scaled = self.base_slippage_pct * (order_value_usd / 10_000.0)
        return min(scaled, self.max_slippage_pct)

    def set_price(self, ticker: str, price: float):
        """Set simulated price for a ticker (for testing).

        Args:
            ticker: Asset ticker symbol
            price: Simulated current price
        """
        self._prices[ticker] = price
        self._check_resting_stops(ticker, price)

    def set_prices(self, prices: Dict[str, float]):
        """Set simulated prices for multiple tickers."""
        self._prices.update(prices)
        for ticker, price in prices.items():
            self._check_resting_stops(ticker, price)

    # ── Protective stop simulation ────────────────────────────────────
    #
    # Paper mode must model stops, not ignore them. A simulator that fills
    # entries but never fires stops reports the P&L of a strategy that
    # never cuts a loss — flattering exactly the scenarios (fast adverse
    # moves) that a stop exists for, and giving false confidence before
    # real money is committed.

    def place_stop_loss_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        stop_price: float,
        position_side: Optional[str] = None,
    ) -> OrderResult:
        """Register a resting protective stop, triggered by later price updates."""
        order_id = f"paper_stop_{uuid.uuid4().hex[:12]}"
        self._resting_stops[order_id] = {
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "stop_price": stop_price,
        }
        logger.info(
            "[PaperBroker] Protective stop registered: %s %s %s @ trigger %.8f",
            side.value, quantity, ticker, stop_price,
        )
        return OrderResult(
            order_id=order_id,
            ticker=ticker,
            side=side,
            order_type=OrderType.STOP,
            status=OrderStatus.SUBMITTED,
            requested_quantity=quantity,
            requested_price=stop_price,
            broker_name=self.name,
        )

    def _check_resting_stops(self, ticker: str, price: float) -> None:
        """Fire any resting stop whose trigger the new price has crossed."""
        triggered = [
            oid for oid, s in self._resting_stops.items()
            if s["ticker"] == ticker and (
                (s["side"] == OrderSide.SELL and price <= s["stop_price"])   # protecting a long
                or (s["side"] == OrderSide.BUY and price >= s["stop_price"])  # protecting a short
            )
        ]
        for oid in triggered:
            stop = self._resting_stops.pop(oid)
            logger.warning(
                "[PaperBroker] STOP TRIGGERED %s: price %.8f crossed %.8f — closing %s",
                ticker, price, stop["stop_price"], stop["quantity"],
            )
            self.place_order(
                ticker=ticker,
                side=stop["side"],
                quantity=stop["quantity"],
                order_type=OrderType.MARKET,
            )

    def cancel_stop_loss_order(self, order_id: str) -> bool:
        """Remove a resting stop (e.g. when its position is closed another way)."""
        return self._resting_stops.pop(order_id, None) is not None

    def place_order(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> OrderResult:
        """Execute a simulated trade with volume-based slippage and commission."""
        order_id = f"paper_{uuid.uuid4().hex[:12]}"

        # Determine fill price
        base_price = limit_price or self._prices.get(ticker)
        if base_price is None:
            return OrderResult(
                order_id=order_id,
                ticker=ticker,
                side=side,
                order_type=order_type,
                status=OrderStatus.REJECTED,
                requested_quantity=quantity,
                error_message=f"No price available for {ticker}. Use set_price() or provide limit_price.",
                broker_name=self.name,
            )

        # Calculate volume-based slippage
        order_value = base_price * quantity
        effective_slippage = self._calculate_slippage(order_value)

        if side == OrderSide.BUY:
            fill_price = base_price * (1 + effective_slippage)
        else:
            fill_price = base_price * (1 - effective_slippage)

        # Calculate cost and commission
        trade_value = fill_price * quantity
        commission = trade_value * self.commission_pct

        # Check for LIMIT order price conditions
        if order_type == OrderType.LIMIT and limit_price is not None:
            current = self._prices.get(ticker, limit_price)
            if side == OrderSide.BUY and current > limit_price:
                return OrderResult(
                    order_id=order_id,
                    ticker=ticker,
                    side=side,
                    order_type=order_type,
                    status=OrderStatus.PENDING,
                    requested_quantity=quantity,
                    requested_price=limit_price,
                    remaining_quantity=quantity,
                    broker_name=self.name,
                )
            elif side == OrderSide.SELL and current < limit_price:
                return OrderResult(
                    order_id=order_id,
                    ticker=ticker,
                    side=side,
                    order_type=order_type,
                    status=OrderStatus.PENDING,
                    requested_quantity=quantity,
                    requested_price=limit_price,
                    remaining_quantity=quantity,
                    broker_name=self.name,
                )

        # Check sufficient funds for BUY
        if side == OrderSide.BUY:
            total_cost = trade_value + commission
            if total_cost > self.cash_balance:
                return OrderResult(
                    order_id=order_id,
                    ticker=ticker,
                    side=side,
                    order_type=order_type,
                    status=OrderStatus.REJECTED,
                    requested_quantity=quantity,
                    requested_price=base_price,
                    error_message=f"Insufficient funds: need ${total_cost:,.2f}, have ${self.cash_balance:,.2f}",
                    broker_name=self.name,
                )

            # Deduct cash
            self.cash_balance -= total_cost

            # Add or increase position
            if ticker in self._positions:
                pos = self._positions[ticker]
                # Average up
                total_qty = pos["quantity"] + quantity
                avg_price = ((pos["entry_price"] * pos["quantity"]) + (fill_price * quantity)) / total_qty
                pos["quantity"] = total_qty
                pos["entry_price"] = avg_price
            else:
                self._positions[ticker] = {
                    "side": OrderSide.BUY,
                    "quantity": quantity,
                    "entry_price": fill_price,
                    "entry_time": datetime.utcnow(),
                }

        elif side == OrderSide.SELL:
            # Check if we have a position to sell
            if ticker in self._positions:
                pos = self._positions[ticker]
                sell_qty = min(quantity, pos["quantity"])
                proceeds = sell_qty * fill_price - commission

                self.cash_balance += proceeds
                pos["quantity"] -= sell_qty

                if pos["quantity"] <= 0:
                    del self._positions[ticker]

                quantity = sell_qty  # Actual filled quantity
            else:
                # Short selling (simplified)
                self._positions[ticker] = {
                    "side": OrderSide.SELL,
                    "quantity": quantity,
                    "entry_price": fill_price,
                    "entry_time": datetime.utcnow(),
                }
                self.cash_balance += trade_value - commission

        # Create filled result
        result = OrderResult(
            order_id=order_id,
            ticker=ticker,
            side=side,
            order_type=order_type,
            status=OrderStatus.FILLED,
            requested_quantity=quantity,
            filled_quantity=quantity,
            remaining_quantity=0.0,
            requested_price=base_price,
            filled_price=fill_price,
            average_fill_price=fill_price,
            commission=commission,
            broker_name=self.name,
        )

        self._orders[order_id] = result

        action = "Bought" if side == OrderSide.BUY else "Sold"
        print(
            f"[PaperBroker] {action} {quantity} {ticker} @ ${fill_price:,.4f} "
            f"(slippage: {effective_slippage:.4%} | commission: ${commission:,.4f} | cash: ${self.cash_balance:,.2f})"
        )

        return result

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Cancel a pending order (symbol is accepted but not used)."""
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.status == OrderStatus.PENDING:
                self._orders[order_id] = order.model_copy(
                    update={"status": OrderStatus.CANCELLED}
                )
                return True
        return False

    def get_order_status(self, order_id: str) -> OrderResult:
        """Get order status."""
        if order_id in self._orders:
            return self._orders[order_id]
        return OrderResult(
            order_id=order_id,
            ticker="UNKNOWN",
            side=OrderSide.BUY,
            status=OrderStatus.REJECTED,
            requested_quantity=0,
            error_message=f"Order {order_id} not found",
            broker_name=self.name,
        )

    def get_balance(self) -> Dict[str, float]:
        """Get current account balance."""
        positions_value = sum(
            self._prices.get(ticker, pos["entry_price"]) * pos["quantity"]
            for ticker, pos in self._positions.items()
        )
        total_equity = self.cash_balance + positions_value

        return {
            "cash": self.cash_balance,
            "positions_value": positions_value,
            "total_equity": total_equity,
            "buying_power": self.cash_balance,
            "initial_cash": self.initial_cash,
            "pnl": total_equity - self.initial_cash,
        }

    def get_positions(self) -> List[PositionInfo]:
        """Get all open positions."""
        positions = []
        for ticker, pos in self._positions.items():
            current_price = self._prices.get(ticker, pos["entry_price"])
            positions.append(
                PositionInfo(
                    ticker=ticker,
                    side=pos["side"],
                    quantity=pos["quantity"],
                    entry_price=pos["entry_price"],
                    current_price=current_price,
                    entry_timestamp=pos["entry_time"],
                )
            )
        return positions

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get simulated current price."""
        return self._prices.get(ticker)

    def reset(self):
        """Reset the paper broker to initial state."""
        self.cash_balance = self.initial_cash
        self._positions.clear()
        self._orders.clear()
        self._prices.clear()
        print(f"[PaperBroker] Reset to ${self.initial_cash:,.2f}")
