"""Position tracking utilities for monitoring and managing open positions.

Provides higher-level position monitoring logic such as trailing stops,
time-based exits, and position health checks.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

from tradingagents.execution.order_models import PositionInfo, OrderSide


class PositionTracker:
    """Monitors open positions and provides alerting for exit conditions.

    Works alongside PortfolioManager to provide advanced position monitoring
    features like trailing stops and time-based exit rules.
    """

    def __init__(
        self,
        trailing_stop_pct: float = 0.0,
        max_hold_days: int = 0,
    ):
        """Initialize the position tracker.

        Args:
            trailing_stop_pct: Trailing stop percentage (0.0 = disabled, e.g., 0.05 = 5%)
            max_hold_days: Maximum days to hold a position (0 = unlimited)
        """
        self.trailing_stop_pct = trailing_stop_pct
        self.max_hold_days = max_hold_days

        # Track the highest price seen since entry for trailing stop
        # ticker -> highest price (for long) or lowest price (for short)
        self._peak_prices: Dict[str, float] = {}

    def register_position(self, position: PositionInfo):
        """Register a new position for tracking.

        Args:
            position: The position to start tracking
        """
        self._peak_prices[position.ticker] = position.entry_price

    def unregister_position(self, ticker: str):
        """Remove a position from tracking.

        Args:
            ticker: Ticker symbol to remove
        """
        self._peak_prices.pop(ticker, None)

    def update_price(self, ticker: str, current_price: float, side: OrderSide):
        """Update the price tracking for trailing stop calculations.

        Args:
            ticker: Asset ticker
            current_price: Current market price
            side: Position side (BUY or SELL)
        """
        if ticker not in self._peak_prices:
            self._peak_prices[ticker] = current_price
            return

        if side == OrderSide.BUY:
            # For long positions, track the highest price
            if current_price > self._peak_prices[ticker]:
                self._peak_prices[ticker] = current_price
        else:
            # For short positions, track the lowest price
            if current_price < self._peak_prices[ticker]:
                self._peak_prices[ticker] = current_price

    def check_trailing_stop(
        self, position: PositionInfo
    ) -> Optional[Dict[str, Any]]:
        """Check if trailing stop should trigger for a position.

        Args:
            position: The position to check

        Returns:
            Dict with trigger info or None if not triggered
        """
        if self.trailing_stop_pct <= 0:
            return None

        ticker = position.ticker
        if ticker not in self._peak_prices:
            return None

        peak = self._peak_prices[ticker]
        current = position.current_price

        if position.side == OrderSide.BUY:
            # Long: trigger if price drops trailing_stop_pct from peak
            trailing_stop_price = peak * (1 - self.trailing_stop_pct)
            if current <= trailing_stop_price:
                return {
                    "ticker": ticker,
                    "trigger": "trailing_stop",
                    "peak_price": peak,
                    "trailing_stop_price": trailing_stop_price,
                    "current_price": current,
                    "drop_pct": (peak - current) / peak,
                }
        else:
            # Short: trigger if price rises trailing_stop_pct from trough
            trailing_stop_price = peak * (1 + self.trailing_stop_pct)
            if current >= trailing_stop_price:
                return {
                    "ticker": ticker,
                    "trigger": "trailing_stop",
                    "trough_price": peak,
                    "trailing_stop_price": trailing_stop_price,
                    "current_price": current,
                    "rise_pct": (current - peak) / peak,
                }

        return None

    def check_time_exit(self, position: PositionInfo) -> Optional[Dict[str, Any]]:
        """Check if a position should be closed due to time limit.

        Args:
            position: The position to check

        Returns:
            Dict with trigger info or None if not triggered
        """
        if self.max_hold_days <= 0:
            return None

        hold_duration = datetime.utcnow() - position.entry_timestamp
        max_duration = timedelta(days=self.max_hold_days)

        if hold_duration >= max_duration:
            return {
                "ticker": position.ticker,
                "trigger": "time_exit",
                "held_days": hold_duration.days,
                "max_days": self.max_hold_days,
                "current_price": position.current_price,
                "unrealized_pnl": position.unrealized_pnl,
            }

        return None

    def check_all_exits(
        self, positions: Dict[str, PositionInfo]
    ) -> List[Dict[str, Any]]:
        """Check all positions for any exit conditions.

        Args:
            positions: Dict mapping ticker -> PositionInfo

        Returns:
            List of triggered exit conditions
        """
        triggers = []

        for ticker, position in positions.items():
            # Update price tracking
            self.update_price(ticker, position.current_price, position.side)

            # Check fixed stop-loss / take-profit
            if position.should_stop_loss():
                triggers.append({
                    "ticker": ticker,
                    "trigger": "stop_loss",
                    "stop_loss_price": position.stop_loss_price,
                    "current_price": position.current_price,
                    "unrealized_pnl": position.unrealized_pnl,
                })
            elif position.should_take_profit():
                triggers.append({
                    "ticker": ticker,
                    "trigger": "take_profit",
                    "take_profit_price": position.take_profit_price,
                    "current_price": position.current_price,
                    "unrealized_pnl": position.unrealized_pnl,
                })

            # Check trailing stop
            trailing = self.check_trailing_stop(position)
            if trailing:
                triggers.append(trailing)

            # Check time-based exit
            time_exit = self.check_time_exit(position)
            if time_exit:
                triggers.append(time_exit)

        return triggers

    def get_position_health(self, position: PositionInfo) -> Dict[str, Any]:
        """Get a health assessment for a position.

        Args:
            position: The position to assess

        Returns:
            Dict with health metrics
        """
        hold_duration = datetime.utcnow() - position.entry_timestamp

        health = {
            "ticker": position.ticker,
            "side": position.side.value,
            "hold_duration_hours": hold_duration.total_seconds() / 3600,
            "unrealized_pnl": position.unrealized_pnl,
            "unrealized_pnl_pct": position.unrealized_pnl_pct,
            "has_stop_loss": position.stop_loss_price is not None,
            "has_take_profit": position.take_profit_price is not None,
        }

        # Add distance to stop/take-profit
        if position.stop_loss_price and position.current_price > 0:
            if position.side == OrderSide.BUY:
                health["distance_to_stop_pct"] = (
                    (position.current_price - position.stop_loss_price) / position.current_price
                )
            else:
                health["distance_to_stop_pct"] = (
                    (position.stop_loss_price - position.current_price) / position.current_price
                )

        if position.take_profit_price and position.current_price > 0:
            if position.side == OrderSide.BUY:
                health["distance_to_tp_pct"] = (
                    (position.take_profit_price - position.current_price) / position.current_price
                )
            else:
                health["distance_to_tp_pct"] = (
                    (position.current_price - position.take_profit_price) / position.current_price
                )

        # Health status
        pnl_pct = position.unrealized_pnl_pct
        if pnl_pct > 0.05:
            health["status"] = "healthy"
        elif pnl_pct > -0.02:
            health["status"] = "neutral"
        elif pnl_pct > -0.05:
            health["status"] = "warning"
        else:
            health["status"] = "critical"

        return health
