"""Structured data models for trading decisions and order management.

Replaces free-text BUY/SELL/HOLD output with structured, validated Pydantic models
that can be programmatically processed by execution engines and brokers.
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class TradeAction(str, Enum):
    """Trading action decisions with granularity beyond simple BUY/SELL/HOLD."""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class OrderType(str, Enum):
    """Order execution type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderSide(str, Enum):
    """Order side for broker execution."""
    BUY = "BUY"
    SELL = "SELL"


class MarketType(str, Enum):
    """Market type for exchange trading."""
    SPOT = "spot"
    FUTURES = "future"


class PositionSide(str, Enum):
    """Position direction for futures trading."""
    LONG = "LONG"
    SHORT = "SHORT"


class MarginType(str, Enum):
    """Margin mode for futures trading."""
    ISOLATED = "isolated"
    CROSS = "cross"


class TradeDecision(BaseModel):
    """Structured output from the Trader agent.
    
    This replaces the free-text 'FINAL TRANSACTION PROPOSAL: BUY/SELL/HOLD'
    with a richly structured decision that includes position sizing, risk 
    parameters, and confidence scoring.
    """
    action: TradeAction = Field(
        description="The recommended trade action"
    )
    ticker: str = Field(
        description="Ticker symbol for the asset"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0,
        description="Confidence level in the decision (0.0 = no confidence, 1.0 = absolute confidence)"
    )
    quantity_pct: float = Field(
        ge=0.0, le=1.0, default=0.0,
        description="Percentage of available portfolio to allocate (0.0 to 1.0)"
    )
    order_type: OrderType = Field(
        default=OrderType.MARKET,
        description="Type of order to place"
    )
    limit_price: Optional[float] = Field(
        default=None,
        description="Limit price for LIMIT/STOP_LIMIT orders"
    )
    stop_loss_pct: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Stop-loss as percentage below entry price (e.g., 0.05 = 5%)"
    )
    take_profit_pct: Optional[float] = Field(
        default=None, ge=0.0,
        description="Take-profit as percentage above entry price (e.g., 0.1 = 10%)"
    )
    reasoning: str = Field(
        default="",
        description="Brief reasoning behind the decision"
    )
    key_factors: List[str] = Field(
        default_factory=list,
        description="Top factors that influenced the decision"
    )
    risk_reward_ratio: Optional[float] = Field(
        default=None, ge=0.0,
        description="Estimated risk-reward ratio"
    )
    time_horizon: str = Field(
        default="short_term",
        description="Expected holding period: intraday, short_term, medium_term, long_term"
    )
    # ── Futures-specific fields ────────────────────────────────────────
    leverage: int = Field(
        default=1, ge=1, le=125,
        description="Leverage multiplier (1 = no leverage / spot-equivalent)"
    )
    position_side: PositionSide = Field(
        default=PositionSide.LONG,
        description="Position direction for futures: LONG or SHORT"
    )
    margin_type: MarginType = Field(
        default=MarginType.ISOLATED,
        description="Margin mode: isolated or cross"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the decision was made"
    )

    @field_validator("time_horizon")
    @classmethod
    def validate_time_horizon(cls, v):
        valid = {"intraday", "short_term", "medium_term", "long_term"}
        if v not in valid:
            raise ValueError(f"time_horizon must be one of {valid}")
        return v

    def to_order_side(self) -> Optional[OrderSide]:
        """Convert trade action to order side for broker execution."""
        if self.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            return OrderSide.BUY
        elif self.action in (TradeAction.SELL, TradeAction.STRONG_SELL):
            return OrderSide.SELL
        return None  # HOLD = no order

    def is_actionable(self, min_confidence: float = 0.5) -> bool:
        """Check if this decision should result in an actual trade."""
        if self.action == TradeAction.HOLD:
            return False
        return self.confidence_score >= min_confidence

    def calculate_stop_loss_price(self, entry_price: float) -> Optional[float]:
        """Calculate the absolute stop-loss price from percentage."""
        if self.stop_loss_pct is None:
            return None
        if self.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            return entry_price * (1 - self.stop_loss_pct)
        elif self.action in (TradeAction.SELL, TradeAction.STRONG_SELL):
            return entry_price * (1 + self.stop_loss_pct)
        return None

    def calculate_take_profit_price(self, entry_price: float) -> Optional[float]:
        """Calculate the absolute take-profit price from percentage."""
        if self.take_profit_pct is None:
            return None
        if self.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            return entry_price * (1 + self.take_profit_pct)
        elif self.action in (TradeAction.SELL, TradeAction.STRONG_SELL):
            return entry_price * (1 - self.take_profit_pct)
        return None

    class Config:
        json_schema_extra = {
            "example": {
                "action": "BUY",
                "ticker": "NVDA",
                "confidence_score": 0.82,
                "quantity_pct": 0.15,
                "order_type": "MARKET",
                "stop_loss_pct": 0.05,
                "take_profit_pct": 0.12,
                "reasoning": "Strong momentum with positive earnings surprise and bullish technical signals",
                "key_factors": [
                    "Earnings beat by 15%",
                    "MACD bullish crossover",
                    "Strong institutional buying"
                ],
                "risk_reward_ratio": 2.4,
                "time_horizon": "short_term"
            }
        }


class RiskAssessment(BaseModel):
    """Structured output from the Risk Manager.
    
    Replaces the free-text risk judge output with a structured assessment
    that includes approval status, adjusted parameters, and risk metrics.
    """
    approved: bool = Field(
        description="Whether the trade is approved after risk evaluation"
    )
    original_action: TradeAction = Field(
        description="The original action proposed by the trader"
    )
    adjusted_action: TradeAction = Field(
        description="The action after risk adjustment (may differ from original)"
    )
    adjusted_quantity_pct: float = Field(
        ge=0.0, le=1.0,
        description="Adjusted position size after risk review"
    )
    risk_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall risk score (0.0 = very low risk, 1.0 = extremely risky)"
    )
    max_acceptable_loss: Optional[float] = Field(
        default=None,
        description="Maximum acceptable loss in currency units for this trade"
    )
    adjusted_stop_loss_pct: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Risk-adjusted stop-loss percentage"
    )
    adjusted_take_profit_pct: Optional[float] = Field(
        default=None, ge=0.0,
        description="Risk-adjusted take-profit percentage"
    )
    risk_factors: List[str] = Field(
        default_factory=list,
        description="Key risk factors identified"
    )
    mitigation_notes: str = Field(
        default="",
        description="Notes on risk mitigation strategies applied"
    )
    reasoning: str = Field(
        default="",
        description="Detailed reasoning for the risk assessment"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the assessment was made"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "approved": True,
                "original_action": "STRONG_BUY",
                "adjusted_action": "BUY",
                "adjusted_quantity_pct": 0.10,
                "risk_score": 0.45,
                "max_acceptable_loss": 500.0,
                "adjusted_stop_loss_pct": 0.04,
                "adjusted_take_profit_pct": 0.08,
                "risk_factors": [
                    "High market volatility (VIX > 25)",
                    "Concentrated sector exposure"
                ],
                "mitigation_notes": "Reduced position size from 15% to 10% due to elevated volatility",
                "reasoning": "Trade approved with adjustments. Fundamentals support the position but current volatility warrants smaller allocation."
            }
        }


class OrderStatus(str, Enum):
    """Status of a submitted order."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderResult(BaseModel):
    """Result returned by a broker after order submission.

    Captures the full lifecycle of an order from submission through execution.
    """
    order_id: str = Field(description="Unique order identifier from the broker")
    idempotency_key: Optional[str] = Field(default=None, description="Client-side idempotency key to prevent double orders")
    ticker: str = Field(description="Asset ticker symbol")
    side: OrderSide = Field(description="Order side (BUY/SELL)")
    order_type: OrderType = Field(default=OrderType.MARKET)
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    requested_quantity: float = Field(ge=0.0, description="Quantity requested")
    filled_quantity: float = Field(default=0.0, ge=0.0, description="Quantity filled so far")
    remaining_quantity: float = Field(default=0.0, ge=0.0, description="Quantity remaining to fill")
    requested_price: Optional[float] = Field(default=None, description="Requested price (for limit orders)")
    filled_price: Optional[float] = Field(default=None, description="Average fill price across all partial fills")
    average_fill_price: Optional[float] = Field(default=None, description="Weighted average fill price (for partial fills)")
    commission: float = Field(default=0.0, ge=0.0, description="Commission/fee charged")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error_message: Optional[str] = Field(default=None, description="Error message if order failed")
    broker_name: str = Field(default="unknown", description="Name of the broker that handled this order")
    raw_response: Optional[dict] = Field(default=None, description="Raw broker response for debugging")

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED

    @property
    def is_partial(self) -> bool:
        return self.status == OrderStatus.PARTIALLY_FILLED

    @property
    def is_failed(self) -> bool:
        return self.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED)

    @property
    def effective_fill_price(self) -> Optional[float]:
        """Best available fill price: average_fill_price > filled_price."""
        return self.average_fill_price or self.filled_price

    @property
    def total_cost(self) -> float:
        """Total cost including commission."""
        price = self.effective_fill_price
        if price and self.filled_quantity:
            return (price * self.filled_quantity) + self.commission
        return 0.0


class PositionInfo(BaseModel):
    """Represents a single open position in the portfolio."""
    ticker: str
    side: OrderSide
    quantity: float = Field(ge=0.0)
    entry_price: float = Field(gt=0.0)
    current_price: float = Field(gt=0.0)
    entry_timestamp: datetime
    stop_loss_price: Optional[float] = None
    # ── Futures-specific fields ────────────────────────────────────────
    position_side: PositionSide = Field(default=PositionSide.LONG)
    leverage: int = Field(default=1, ge=1)
    liquidation_price: Optional[float] = None
    margin_type: MarginType = Field(default=MarginType.ISOLATED)
    take_profit_price: Optional[float] = None

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized profit/loss."""
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        """Calculate unrealized P&L as a percentage."""
        cost_basis = self.entry_price * self.quantity
        if cost_basis == 0:
            return 0.0
        return self.unrealized_pnl / cost_basis

    @property
    def market_value(self) -> float:
        """Current market value of the position."""
        return self.current_price * self.quantity

    @property
    def cost_basis(self) -> float:
        """Total cost basis of the position."""
        return self.entry_price * self.quantity

    def should_stop_loss(self) -> bool:
        """Check if stop-loss should be triggered."""
        if self.stop_loss_price is None:
            return False
        if self.side == OrderSide.BUY:
            return self.current_price <= self.stop_loss_price
        else:
            return self.current_price >= self.stop_loss_price

    def should_take_profit(self) -> bool:
        """Check if take-profit should be triggered."""
        if self.take_profit_price is None:
            return False
        if self.side == OrderSide.BUY:
            return self.current_price >= self.take_profit_price
        else:
            return self.current_price <= self.take_profit_price


class PortfolioState(BaseModel):
    """Represents the complete portfolio state that is injected into agent context.
    
    This gives all agents awareness of the current portfolio situation,
    enabling them to make decisions informed by existing positions and risk exposure.
    """
    cash_balance: float = Field(
        default=10000.0, ge=0.0,
        description="Available cash balance"
    )
    total_equity: float = Field(
        default=10000.0, ge=0.0,
        description="Total portfolio value (cash + positions)"
    )
    open_positions: List[PositionInfo] = Field(
        default_factory=list,
        description="Currently open positions"
    )
    daily_pnl: float = Field(
        default=0.0,
        description="Profit/loss for current trading day"
    )
    total_pnl: float = Field(
        default=0.0,
        description="All-time total profit/loss"
    )
    win_rate: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Historical win rate (percentage of profitable trades)"
    )
    total_trades: int = Field(
        default=0, ge=0,
        description="Total number of completed trades"
    )
    max_drawdown_pct: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Maximum drawdown experienced as percentage"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this snapshot was taken"
    )

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.open_positions)

    @property
    def total_unrealized_pnl(self) -> float:
        """Total unrealized P&L across all positions."""
        return sum(p.unrealized_pnl for p in self.open_positions)

    @property
    def total_exposure(self) -> float:
        """Total market value of all positions."""
        return sum(p.market_value for p in self.open_positions)

    @property
    def exposure_pct(self) -> float:
        """Portfolio exposure as percentage of total equity."""
        if self.total_equity == 0:
            return 0.0
        return self.total_exposure / self.total_equity

    def has_position(self, ticker: str) -> bool:
        """Check if there's an existing position for a ticker."""
        return any(p.ticker == ticker for p in self.open_positions)

    def get_position(self, ticker: str) -> Optional[PositionInfo]:
        """Get position info for a specific ticker."""
        for p in self.open_positions:
            if p.ticker == ticker:
                return p
        return None

    def available_for_trading(self, max_position_pct: float = 0.1) -> float:
        """Calculate the maximum amount available for a new trade."""
        max_per_trade = self.total_equity * max_position_pct
        return min(self.cash_balance, max_per_trade)

    def to_agent_context(self) -> str:
        """Format portfolio state as a string for injection into agent prompts."""
        lines = [
            "=== CURRENT PORTFOLIO STATE ===",
            f"Cash Balance: ${self.cash_balance:,.2f}",
            f"Total Equity: ${self.total_equity:,.2f}",
            f"Open Positions: {self.position_count}",
            f"Total Exposure: ${self.total_exposure:,.2f} ({self.exposure_pct:.1%})",
            f"Unrealized P&L: ${self.total_unrealized_pnl:,.2f}",
            f"Daily P&L: ${self.daily_pnl:,.2f}",
            f"All-time P&L: ${self.total_pnl:,.2f}",
            f"Win Rate: {self.win_rate:.1%} ({self.total_trades} trades)",
            f"Max Drawdown: {self.max_drawdown_pct:.1%}",
        ]

        if self.open_positions:
            lines.append("\n--- Open Positions ---")
            for p in self.open_positions:
                pnl_str = f"+${p.unrealized_pnl:,.2f}" if p.unrealized_pnl >= 0 else f"-${abs(p.unrealized_pnl):,.2f}"
                sl_str = f"SL: ${p.stop_loss_price:,.2f}" if p.stop_loss_price else "SL: None"
                tp_str = f"TP: ${p.take_profit_price:,.2f}" if p.take_profit_price else "TP: None"
                lines.append(
                    f"  {p.ticker} | {p.side.value} | Qty: {p.quantity} | "
                    f"Entry: ${p.entry_price:,.2f} | Current: ${p.current_price:,.2f} | "
                    f"P&L: {pnl_str} ({p.unrealized_pnl_pct:+.1%}) | {sl_str} | {tp_str}"
                )
        else:
            lines.append("\nNo open positions.")

        lines.append("=" * 35)
        return "\n".join(lines)
