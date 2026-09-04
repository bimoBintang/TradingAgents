"""Portfolio manager for tracking positions, balance, and P&L.

Provides a centralized view of the portfolio state that gets injected
into agent prompts so they can make position-aware decisions.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

from tradingagents.execution.order_models import (
    PositionInfo,
    PortfolioState,
    OrderSide,
    TradeDecision,
    TradeAction,
)


class TradeRecord:
    """Record of a completed trade (entry + exit)."""

    def __init__(
        self,
        ticker: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        entry_time: datetime,
        exit_time: datetime,
        pnl: float,
        reasoning: str = "",
    ):
        self.ticker = ticker
        self.side = side
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.quantity = quantity
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.pnl = pnl
        self.reasoning = reasoning

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "pnl": self.pnl,
            "reasoning": self.reasoning,
        }


class PortfolioManager:
    """Manages portfolio state including positions, cash, and trade history.

    This is the central truth source for all portfolio-related information.
    It provides methods to open/close positions, calculate P&L, and
    generate portfolio context strings for agent prompt injection.
    """

    def __init__(
        self,
        initial_cash: float = 10000.0,
        max_position_pct: float = 0.1,
        max_total_positions: int = 10,
        state_file: Optional[str] = None,
        kelly_enabled: bool = False,
        kelly_multiplier: float = 0.25,
    ):
        """Initialize the portfolio manager.

        Args:
            initial_cash: Starting cash balance
            max_position_pct: Maximum percentage of portfolio per position (0.0-1.0)
            max_total_positions: Maximum number of concurrent positions
            state_file: Optional file path to persist state (JSON)
            kelly_enabled: Cap position size by fractional Kelly computed
                from this portfolio's own realized trade history. Off by
                default: with too few completed trades there is no edge to
                measure, and the cap would just be noise. See
                kelly_cap_pct() for the safeguards.
            kelly_multiplier: 0.25 = quarter-Kelly (default), 0.5 = half-Kelly.
        """
        self.initial_cash = initial_cash
        self.cash_balance = initial_cash
        self.max_position_pct = max_position_pct
        self.max_total_positions = max_total_positions
        self.state_file = state_file
        self.kelly_enabled = kelly_enabled
        self.kelly_multiplier = kelly_multiplier

        # Open positions: ticker -> PositionInfo
        self.positions: Dict[str, PositionInfo] = {}

        # Trade history
        self.trade_history: List[TradeRecord] = []

        # Performance tracking
        self.peak_equity = initial_cash
        self.daily_starting_equity = initial_cash
        self.total_pnl = 0.0

        # Load persisted state if available
        if state_file:
            self._load_state()

    # ── Position Management ───────────────────────────────────────────

    def open_position(
        self,
        ticker: str,
        side: OrderSide,
        quantity: float,
        entry_price: float,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> bool:
        """Open a new position.

        Args:
            ticker: Asset ticker symbol
            side: BUY (long) or SELL (short)
            quantity: Number of units
            entry_price: Price at which position is entered
            stop_loss_price: Optional stop-loss price
            take_profit_price: Optional take-profit price

        Returns:
            True if position was opened successfully
        """
        if ticker in self.positions:
            logger.warning("Already have position in %s. Use add_to_position() instead.", ticker)
            return False

        if len(self.positions) >= self.max_total_positions:
            logger.warning("Maximum positions (%d) reached.", self.max_total_positions)
            return False

        cost = quantity * entry_price
        if cost > self.cash_balance:
            logger.warning("Insufficient cash. Need $%.2f, have $%.2f", cost, self.cash_balance)
            return False

        # Deduct cash
        self.cash_balance -= cost

        # Create position
        self.positions[ticker] = PositionInfo(
            ticker=ticker,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            entry_timestamp=datetime.utcnow(),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
        )

        logger.info(
            "Opened %s %s %s @ $%.2f (Cost: $%.2f | Cash remaining: $%.2f)",
            side.value, quantity, ticker, entry_price, cost, self.cash_balance,
        )

        self._save_state()
        return True

    def close_position(
        self,
        ticker: str,
        exit_price: float,
        reasoning: str = "",
    ) -> Optional[float]:
        """Close an existing position.

        Args:
            ticker: Asset ticker symbol
            exit_price: Price at which position is closed
            reasoning: Reason for closing

        Returns:
            Realized P&L or None if no position exists
        """
        if ticker not in self.positions:
            logger.warning("No position found for %s", ticker)
            return None

        position = self.positions[ticker]
        position.current_price = exit_price

        # Calculate P&L
        pnl = position.unrealized_pnl
        proceeds = position.quantity * exit_price

        # Return cash + P&L
        self.cash_balance += proceeds
        self.total_pnl += pnl

        # Record trade
        trade = TradeRecord(
            ticker=ticker,
            side=position.side.value,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            entry_time=position.entry_timestamp,
            exit_time=datetime.utcnow(),
            pnl=pnl,
            reasoning=reasoning,
        )
        self.trade_history.append(trade)

        # Remove position
        del self.positions[ticker]

        pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
        logger.info(
            "Closed %s %s %s @ $%.2f (P&L: %s | Cash: $%.2f)",
            trade.side, trade.quantity, ticker, exit_price, pnl_str, self.cash_balance,
        )

        self._save_state()
        return pnl

    def update_prices(self, price_updates: Dict[str, float]):
        """Update current prices for all open positions.

        Args:
            price_updates: Dict mapping ticker -> current price
        """
        for ticker, price in price_updates.items():
            if ticker in self.positions:
                self.positions[ticker].current_price = price

        # Update peak equity for drawdown tracking
        equity = self.total_equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    # ── Position Sizing ───────────────────────────────────────────────

    def kelly_cap_pct(self) -> Optional[float]:
        """Fractional-Kelly ceiling on allocation, from realized trade history.

        Returns None when there is no statistically usable edge yet — the
        caller must then fall back to its normal cap rather than treating
        None as zero.

        Deliberately computed from THIS portfolio's own closed trades
        (real fills, real slippage), never from backtest output. Sizing off
        the same data a strategy was tuned on is how Kelly turns
        overfitting into leverage.
        """
        if not self.kelly_enabled:
            return None

        from tradingagents.execution.position_sizing import (
            kelly_fraction_continuous, MIN_TRADES_FOR_EDGE,
        )

        returns: List[float] = []
        for t in self.trade_history:
            notional = t.entry_price * t.quantity
            if notional > 0:
                returns.append(t.pnl / notional)

        if len(returns) < MIN_TRADES_FOR_EDGE:
            return None

        kelly = kelly_fraction_continuous(
            returns,
            kelly_multiplier=self.kelly_multiplier,
            max_fraction=self.max_position_pct,
        )
        return kelly if kelly > 0 else None

    def calculate_position_size(
        self,
        decision: TradeDecision,
        current_price: float,
    ) -> float:
        """Calculate the number of units to buy/sell based on decision and portfolio constraints.

        Args:
            decision: The structured trade decision
            current_price: Current market price of the asset

        Returns:
            Number of units (quantity) to trade
        """
        if decision.action == TradeAction.HOLD:
            return 0.0

        # Cap allocation at max_position_pct
        allocation_pct = min(decision.quantity_pct, self.max_position_pct)

        # Optional Kelly ceiling — can only SHRINK the allocation, never
        # grow it. If the measured edge justifies more than the agent
        # asked for, we still defer to the agent's (smaller) number:
        # Kelly's job here is to veto oversizing, not to encourage it.
        kelly_cap = self.kelly_cap_pct()
        if kelly_cap is not None and kelly_cap < allocation_pct:
            logger.info(
                "Kelly cap applied: %.2f%% -> %.2f%% (from %d closed trades)",
                allocation_pct * 100, kelly_cap * 100, len(self.trade_history),
            )
            allocation_pct = kelly_cap

        # Calculate dollar amount
        dollar_amount = self.total_equity * allocation_pct

        # Don't exceed available cash
        dollar_amount = min(dollar_amount, self.cash_balance)

        if dollar_amount <= 0 or current_price <= 0:
            return 0.0

        # Calculate quantity
        quantity = dollar_amount / current_price

        return round(quantity, 8)  # 8 decimals for crypto compatibility

    # ── Portfolio State ───────────────────────────────────────────────

    @property
    def total_equity(self) -> float:
        """Total portfolio value = cash + positions market value."""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash_balance + positions_value

    @property
    def total_unrealized_pnl(self) -> float:
        """Total unrealized P&L across all open positions."""
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def daily_pnl(self) -> float:
        """P&L since the start of the current trading day."""
        return self.total_equity - self.daily_starting_equity

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum drawdown from peak equity."""
        if self.peak_equity == 0:
            return 0.0
        dd = (self.peak_equity - self.total_equity) / self.peak_equity
        return max(0.0, dd)  # Clamp: equity above peak → 0% drawdown

    @property
    def win_rate(self) -> float:
        """Historical win rate."""
        if not self.trade_history:
            return 0.0
        wins = sum(1 for t in self.trade_history if t.pnl > 0)
        return wins / len(self.trade_history)

    @property
    def total_trades(self) -> int:
        """Total number of completed trades."""
        return len(self.trade_history)

    def get_portfolio_state(self) -> PortfolioState:
        """Get a snapshot of the current portfolio state.

        Returns:
            PortfolioState object that can be serialized and injected into agent prompts
        """
        return PortfolioState(
            cash_balance=self.cash_balance,
            total_equity=self.total_equity,
            open_positions=list(self.positions.values()),
            daily_pnl=self.daily_pnl,
            total_pnl=self.total_pnl,
            win_rate=self.win_rate,
            total_trades=self.total_trades,
            max_drawdown_pct=self.max_drawdown_pct,
        )

    def get_portfolio_context_string(self) -> str:
        """Get portfolio state formatted as a string for agent prompt injection.

        Returns:
            Human-readable portfolio summary string
        """
        return self.get_portfolio_state().to_agent_context()

    # ── Trade History ─────────────────────────────────────────────────

    def get_recent_trades(self, n: int = 10) -> List[TradeRecord]:
        """Get the N most recent completed trades."""
        return self.trade_history[-n:]

    def get_trade_summary(self) -> str:
        """Get a summary of trading performance."""
        if not self.trade_history:
            return "No completed trades yet."

        total = len(self.trade_history)
        wins = sum(1 for t in self.trade_history if t.pnl > 0)
        losses = total - wins
        total_pnl = sum(t.pnl for t in self.trade_history)
        avg_win = (
            sum(t.pnl for t in self.trade_history if t.pnl > 0) / wins
            if wins > 0
            else 0
        )
        avg_loss = (
            sum(t.pnl for t in self.trade_history if t.pnl <= 0) / losses
            if losses > 0
            else 0
        )

        lines = [
            "=== TRADE PERFORMANCE SUMMARY ===",
            f"Total Trades: {total}",
            f"Wins: {wins} | Losses: {losses} | Win Rate: {self.win_rate:.1%}",
            f"Total P&L: ${total_pnl:,.2f}",
            f"Avg Win: ${avg_win:,.2f} | Avg Loss: ${avg_loss:,.2f}",
            f"Profit Factor: {abs(avg_win / avg_loss) if avg_loss != 0 else 'N/A'}",
            f"Max Drawdown: {self.max_drawdown_pct:.1%}",
            "=" * 35,
        ]
        return "\n".join(lines)

    # ── Checks for Stop-Loss / Take-Profit ────────────────────────────

    def check_stop_loss_take_profit(self) -> List[Dict[str, Any]]:
        """Check all positions for stop-loss or take-profit triggers.

        Returns:
            List of dicts describing triggered exits:
            [{"ticker": ..., "trigger": "stop_loss"|"take_profit", "price": ...}, ...]
        """
        triggered = []
        for ticker, position in self.positions.items():
            if position.should_stop_loss():
                triggered.append({
                    "ticker": ticker,
                    "trigger": "stop_loss",
                    "price": position.stop_loss_price,
                    "current_price": position.current_price,
                })
            elif position.should_take_profit():
                triggered.append({
                    "ticker": ticker,
                    "trigger": "take_profit",
                    "price": position.take_profit_price,
                    "current_price": position.current_price,
                })
        return triggered

    # ── Day Reset ─────────────────────────────────────────────────────

    def reset_daily_tracking(self):
        """Reset daily P&L tracking. Call at the start of each trading day."""
        self.daily_starting_equity = self.total_equity

    # ── Persistence ───────────────────────────────────────────────────

    def _save_state(self):
        """Save portfolio state to JSON file."""
        if not self.state_file:
            return

        state = {
            "cash_balance": self.cash_balance,
            "initial_cash": self.initial_cash,
            "peak_equity": self.peak_equity,
            "daily_starting_equity": self.daily_starting_equity,
            "total_pnl": self.total_pnl,
            "positions": {
                ticker: pos.model_dump(mode="json")
                for ticker, pos in self.positions.items()
            },
            "trade_history": [t.to_dict() for t in self.trade_history],
            "saved_at": datetime.utcnow().isoformat(),
        }

        path = Path(self.state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

    def _load_state(self):
        """Load portfolio state from JSON file."""
        if not self.state_file:
            return

        path = Path(self.state_file)
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)

            self.cash_balance = state.get("cash_balance", self.initial_cash)
            self.initial_cash = state.get("initial_cash", self.initial_cash)
            self.peak_equity = state.get("peak_equity", self.initial_cash)
            self.daily_starting_equity = state.get("daily_starting_equity", self.initial_cash)
            self.total_pnl = state.get("total_pnl", 0.0)

            # Restore positions
            self.positions = {}
            for ticker, pos_data in state.get("positions", {}).items():
                self.positions[ticker] = PositionInfo(**pos_data)

            # Restore trade history
            self.trade_history = []
            for t_data in state.get("trade_history", []):
                t_data["entry_time"] = datetime.fromisoformat(t_data["entry_time"])
                t_data["exit_time"] = datetime.fromisoformat(t_data["exit_time"])
                self.trade_history.append(TradeRecord(**t_data))

            logger.info("Loaded state from %s (Cash: $%.2f, Positions: %d)",
                        self.state_file, self.cash_balance, len(self.positions))

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load state: %s. Starting fresh.", e)
