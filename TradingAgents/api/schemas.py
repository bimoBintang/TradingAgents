"""Pydantic schemas for FastAPI request / response models."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum

# ── Request Models ────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """POST /api/auth/login body."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class RegisterRequest(BaseModel):
    """POST /api/auth/register body."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="Password (min 6 chars)")
    name: str = Field(..., description="Display name")


# ── Auth Response Models ─────────────────────────────────────────────

class UserResponse(BaseModel):
    email: str
    name: str
    is_admin: bool = False
    created_at: str


class AuthResponse(BaseModel):
    user: UserResponse


class AnalyzeRequest(BaseModel):
    """POST /api/analyze body."""
    ticker: str = Field(..., description="Ticker symbol, e.g. NVDA")
    trade_date: Optional[str] = Field(
        None, description="Date for analysis (YYYY-MM-DD). Defaults to today."
    )
    auto_execute: bool = Field(
        False, description="Auto-execute the trade decision via the broker."
    )


class ConfigUpdateRequest(BaseModel):
    """PUT /api/config body — partial config update."""
    updates: Dict[str, Any] = Field(
        ..., description="Dictionary of config keys to update."
    )


class ExecutionConfigUpdate(BaseModel):
    """Validated sub-schema for execution config fields."""
    mode: Optional[str] = Field(None, pattern=r"^(disabled|paper|live)$")
    broker: Optional[str] = Field(None, pattern=r"^(paper|ccxt|alpaca)$")
    exchange: Optional[str] = None
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    password: Optional[str] = None
    market_type: Optional[str] = Field(None, pattern=r"^(spot|future)$")
    margin_type: Optional[str] = Field(None, pattern=r"^(isolated|cross)$")
    max_leverage: Optional[int] = Field(None, ge=1, le=125)
    min_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    require_confirmation: Optional[bool] = None
    quote_currency: Optional[str] = None
    sandbox: Optional[bool] = None
    cooldown_seconds: Optional[int] = Field(None, ge=0, le=86400)
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.01, le=0.5)


class RiskControlsUpdate(BaseModel):
    """Validated sub-schema for risk_controls config fields."""
    kill_switch_enabled: Optional[bool] = None
    max_daily_loss_pct: Optional[float] = Field(None, ge=0.01, le=0.5)
    max_weekly_loss_pct: Optional[float] = Field(None, ge=0.02, le=1.0)
    max_position_pct: Optional[float] = Field(None, ge=0.01, le=1.0)
    max_concurrent_positions: Optional[int] = Field(None, ge=1, le=50)
    trailing_stop_pct: Optional[float] = Field(None, ge=0.0, le=1.0)
    atr_multiplier: Optional[float] = Field(None, ge=0.1, le=10.0)
    max_hold_hours: Optional[int] = Field(None, ge=1, le=720)
    consecutive_loss_limit: Optional[int] = Field(None, ge=1, le=20)
    cooldown_seconds: Optional[int] = Field(None, ge=0, le=86400)


class OrderFlowUpdate(BaseModel):
    """Validated sub-schema for order_flow config fields."""
    enabled: Optional[bool] = None
    obi_execute_threshold: Optional[float] = Field(None, ge=0.0, le=0.9)
    obi_block_threshold: Optional[float] = Field(None, ge=0.0, le=0.9)
    order_book_depth: Optional[int] = Field(None, ge=5, le=100)
    max_wait_seconds: Optional[int] = Field(None, ge=10, le=600)
    poll_interval_seconds: Optional[int] = Field(None, ge=1, le=60)
    wall_detection_usd: Optional[int] = Field(None, ge=10000, le=10000000)


# ── Response Models ───────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: str


class StatusResponse(BaseModel):
    session_id: str
    execution_mode: str
    engine_status: Dict[str, Any]
    uptime_seconds: float


class PositionResponse(BaseModel):
    ticker: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float


class PortfolioResponse(BaseModel):
    cash_balance: float
    total_equity: float
    total_pnl: float
    daily_pnl: Optional[float] = None
    win_rate: float
    max_drawdown_pct: float
    total_trades: int
    open_positions: List[PositionResponse]


class ExitTriggerResponse(BaseModel):
    ticker: str
    trigger: str
    details: Optional[str] = None


class AnalyzeResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str = "Analysis started in background."


class AnalysisResultResponse(BaseModel):
    task_id: str
    status: str  # "running" | "completed" | "failed"
    decision: Optional[Any] = None
    order_result: Optional[Any] = None
    reports: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PerformanceResponse(BaseModel):
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0


class TradeResponse(BaseModel):
    id: Optional[str] = None
    ticker: Optional[str] = None
    action: Optional[str] = None
    filled_qty: Optional[float] = None
    fill_price: Optional[float] = None
    realized_pnl: Optional[float] = None
    status: Optional[str] = None
    fill_time: Optional[str] = None
    created_at: Optional[str] = None


class EquityPointResponse(BaseModel):
    timestamp: str
    total_equity: float
    cash: Optional[float] = None
    drawdown_pct: Optional[float] = None


class ConfigResponse(BaseModel):
    config: Dict[str, Any]


# ── Market Data Models ────────────────────────────────────────────────

class OHLCVCandle(BaseModel):
    """Single OHLCV candle for chart rendering."""
    time: str = Field(..., description="Date string yyyy-mm-dd")
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Price must be > 0, got {v}")
        return round(v, 4)


class OHLCVResponse(BaseModel):
    ticker: str
    interval: str
    candles: List[OHLCVCandle]
    count: int


class FibLevel(BaseModel):
    """Single Fibonacci level."""
    label: str = Field(..., description="e.g. '61.8%'")
    ratio: float
    price: float
    type: str = Field(..., description="'retracement' or 'extension'")

    @field_validator("price")
    @classmethod
    def fib_price_round(cls, v: float) -> float:
        # Extension levels (127.2%, 161.8%, 261.8%) can be negative in
        # strong downtrends — this is mathematically valid, don't reject.
        return round(v, 4)


class FibonacciResponse(BaseModel):
    """Complete Fibonacci analysis response."""
    status: str
    symbol: str
    period: str
    data_points: int
    current_price: float
    swing_high: float
    swing_low: float
    swing_high_date: Optional[str] = None
    swing_low_date: Optional[str] = None
    trend_direction: str
    trend_confidence: float
    is_uptrend: bool
    in_golden_zone: bool
    levels: List[FibLevel]

    @model_validator(mode="after")
    def swing_high_above_low(self) -> "FibonacciResponse":
        if self.swing_high < self.swing_low:
            raise ValueError(
                f"swing_high ({self.swing_high}) must be >= swing_low ({self.swing_low})"
            )
        return self


# ── SMC Models ────────────────────────────────────────────────────────

class FVGZone(BaseModel):
    type: str
    top: float
    bottom: float
    gap_size: float
    candle_date: str
    is_filled: bool
    fill_pct: float

class FVGResponse(BaseModel):
    status: str
    symbol: str
    fvgs: List[FVGZone]

class IFVGZone(BaseModel):
    original_type: str
    inverted_type: str
    top: float
    bottom: float
    original_date: str
    breach_date: str

class IFVGResponse(BaseModel):
    status: str
    symbol: str
    ifvgs: List[IFVGZone]

class SweepEvent(BaseModel):
    type: str
    swing_price: float
    sweep_price: float
    sweep_date: str
    reversal_confirmed: bool

class LiquiditySweepResponse(BaseModel):
    status: str
    symbol: str
    sweeps: List[SweepEvent]

class FlowCandle(BaseModel):
    date: str
    delta: float
    cumulative_delta: float
    buy_vol: float
    sell_vol: float

class OrderFlowSummary(BaseModel):
    net_delta: float
    avg_delta: float
    pressure: str

class OrderFlowResponse(BaseModel):
    status: str
    symbol: str
    flow: List[FlowCandle]
    summary: OrderFlowSummary

class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"

class JournalNoteCreate(BaseModel):
    date: str  # YYYY-MM-DD
    content: str

class JournalNoteResponse(BaseModel):
    id: int
    date: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class VWAPPoint(BaseModel):
    date: str
    vwap: float
    price: float
    deviation_pct: float

class AnchoredVWAPResponse(BaseModel):
    status: str
    symbol: str
    anchor_date: str
    anchor_price: float
    vwap_values: List[VWAPPoint]
    current_deviation_pct: float

class VolumeBucket(BaseModel):
    price_low: float
    price_high: float
    price_mid: float
    volume: float
    pct_of_total: float
    is_value_area: bool
    is_poc: bool

class VolumeProfileResponse(BaseModel):
    status: str
    symbol: str
    poc_price: float
    vah_price: float
    val_price: float
    buckets: List[VolumeBucket]


# ── Polymarket Prediction Markets (Phase 14) ─────────────────────────

class PredictionMarketItem(BaseModel):
    question: str
    yes_price: float
    no_price: float
    yes_pct: float
    volume: float
    condition_id: str = ""

class PredictionEventItem(BaseModel):
    title: str
    slug: str = ""
    description: str = ""
    image: str = ""
    icon: str = ""
    tags: List[str] = []
    volume: float = 0
    liquidity: float = 0
    start_date: str = ""
    end_date: str = ""
    markets: List[PredictionMarketItem] = []

class PredictionMarketsResponse(BaseModel):
    status: str
    query: str
    count: int = 0
    events: List[PredictionEventItem] = []
    message: str = ""

# ── Admin Global Settings (Phase 16) ───────────────────────────────────

class AdminConfig(BaseModel):
    maintenance_mode: bool
    allow_registration: bool
    global_max_leverage: int

class AdminConfigUpdate(BaseModel):
    maintenance_mode: Optional[bool] = None
    allow_registration: Optional[bool] = None
    global_max_leverage: Optional[int] = None


# ── Admin Dashboard Models ────────────────────────────────────────────

class AdminUserItem(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool = False
    created_at: str
    status: str = "active"

class AdminSystemStats(BaseModel):
    total_users: int = 0
    admin_users: int = 0
    total_trades: int = 0
    total_platform_volume: float = 0.0
    total_equity: float = 0.0
    active_positions: int = 0
    engine_uptime_seconds: float = 0.0

class AdminRoleUpdate(BaseModel):
    is_admin: bool

class AdminUserDetailsResponse(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool
    created_at: str
    portfolio_balance: float = 0.0
    total_equity: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    max_drawdown_pct: float = 0.0
    active_positions_count: int = 0


# ── Chart Pattern Detection ──────────────────────────────────────────

class PatternPoint(BaseModel):
    """A single labelled coordinate on the chart."""
    time: int = Field(..., description="Unix timestamp in seconds")
    price: float
    label: str


class ChartPattern(BaseModel):
    """One detected chart pattern."""
    type: str  # "head_and_shoulders" | "rising_wedge" | "falling_wedge"
    points: List[PatternPoint]
    confidence: float = Field(..., ge=0.0, le=1.0)
    direction: str  # "bullish" | "bearish"


class PatternResponse(BaseModel):
    """Response from GET /api/market-data/patterns/{ticker}."""
    ticker: str
    timeframe: str
    candle_count: int
    patterns: List[ChartPattern]
    detected_at: int = Field(..., description="Unix timestamp of detection")


# ── Pending Order Schemas ─────────────────────────────────────────────

class PendingOrderResponse(BaseModel):
    """Single pending order awaiting approval."""
    id: str
    idempotency_key: str
    ticker: str
    action: str                             # BUY, SELL, STRONG_BUY, STRONG_SELL
    quantity: float
    price: float
    value: float
    confidence: float
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    order_type: str = "MARKET"
    time_horizon: Optional[str] = None
    reasoning: str = ""
    key_factors: List[str] = []
    risk_score: Optional[float] = None
    status: str = "PENDING"
    created_at: str = ""
    expires_at: Optional[str] = None


class ApproveRejectResponse(BaseModel):
    """Response from approve/reject endpoints."""
    success: bool
    idempotency_key: str
    status: str                             # APPROVED, REJECTED, FAILED, NOT_FOUND
    message: str
    order_id: Optional[str] = None
