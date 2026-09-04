from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    clerk_id = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    portfolio = relationship("PortfolioState", back_populates="user", uselist=False)
    user_config = relationship("UserConfig", back_populates="user", uselist=False)


class UserConfig(Base):
    """Per-user configuration for multi-tenant isolation.

    Stores all runtime settings (execution, risk_controls, order_flow, etc.)
    as a JSON blob. API credentials are stored separately in encrypted columns
    and NEVER appear inside config_json.
    """
    __tablename__ = "user_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # JSON blob — all config EXCEPT credentials
    config_json = Column(Text, nullable=False, default="{}")

    # Encrypted credentials (Fernet) — never plaintext
    encrypted_api_key = Column(String, default="")
    encrypted_api_secret = Column(String, default="")
    encrypted_password = Column(String, default="")  # OKX / KuCoin passphrase

    # Schema versioning — bumped when DEFAULT_CONFIG adds new required fields
    config_version = Column(Integer, default=1)

    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="user_config")

class PortfolioState(Base):
    __tablename__ = "portfolio_state"
    # Portfolios are mapped 1:1 to Users
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=True) # allow null for legacy logic fallback
    cash_balance = Column(Float, default=100000.0)
    total_equity = Column(Float, default=100000.0)
    total_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, nullable=True)
    win_rate = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="portfolio")
    positions = relationship("Position", back_populates="portfolio")
    trades = relationship("Trade", back_populates="portfolio")

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolio_state.id"))
    ticker = Column(String, index=True, nullable=False)
    side = Column(String, nullable=False) # 'BUY' or 'SELL'
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    unrealized_pnl = Column(Float, default=0.0)

    portfolio = relationship("PortfolioState", back_populates="positions")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolio_state.id"), nullable=True)
    ticker = Column(String, index=True, nullable=False)
    action = Column(String, nullable=False) # 'BUY' or 'SELL'
    filled_qty = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=True)
    status = Column(String, nullable=False)
    fill_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    portfolio = relationship("PortfolioState", back_populates="trades")

class BenchmarkDecision(Base):
    """One strategy's call on one ticker at one moment, resolved forward.

    Exists to answer the only question that justifies running an expensive,
    non-deterministic multi-agent LLM stack: does it beat the dumb
    alternatives? Historical backtesting cannot answer that for an LLM —
    the model's pretraining already covers the period being "predicted",
    so any backtest before its data cutoff is contaminated by lookahead.

    The valid method is forward measurement: at the instant the agent
    decides, record what it chose AND what each baseline would have chosen,
    at the same price, with the same horizon. Resolve them all later
    against real prices. Whatever the comparison then says is honest,
    because none of the strategies could see the outcome.

    One row per (strategy, ticker, decision moment).
    """
    __tablename__ = "benchmark_decisions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    strategy = Column(String, index=True, nullable=False)   # "agent" | "sma_20_50" | "buy_and_hold"
    ticker = Column(String, index=True, nullable=False)
    action = Column(String, nullable=False)                 # BUY | SELL | HOLD
    confidence = Column(Float, nullable=True)

    decided_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    entry_price = Column(Float, nullable=False)
    horizon_days = Column(Integer, default=5)

    # Filled in by resolve_due() once the horizon has elapsed.
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    return_pct = Column(Float, nullable=True)               # direction-signed, net of costs

class EquityCurvePoint(Base):
    """Real, broker-synced equity snapshot — one row per balance_sync tick.

    Exists so max_drawdown_pct can be computed from a true historical
    peak that survives server restarts. PortfolioManager.peak_equity
    (the previous source of that number) is an in-memory value that gets
    reset to the *current* equity every time the process restarts
    (api/db_sync.py's load_graph_from_db) — silently forgetting any real
    drawdown that happened before the restart.
    """
    __tablename__ = "equity_curve_points"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    equity = Column(Float, nullable=False)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

class PlatformConfig(Base):
    __tablename__ = "platform_config"
    id = Column(Integer, primary_key=True, default=1)
    maintenance_mode = Column(Boolean, default=False)
    allow_registration = Column(Boolean, default=True)
    global_max_leverage = Column(Integer, default=50)

class TaskResult(Base):
    """Persistent storage for background analysis task results."""
    __tablename__ = "task_results"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    ticker = Column(String, nullable=False)
    status = Column(String, default="queued")  # queued, running, completed, failed
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class JournalNote(Base):
    """Daily trading journal notes."""
    __tablename__ = "journal_notes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    date = Column(String, index=True, nullable=False)  # Format: YYYY-MM-DD
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User")

class PendingOrder(Base):
    """Trade orders awaiting manual approval before execution.

    When require_confirmation=True, the ExecutionEngine saves the order here
    instead of sending it directly to the broker. The frontend polls for
    pending orders and presents an approval modal.

    Status lifecycle: PENDING → APPROVED / REJECTED / EXPIRED
    """
    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    task_id = Column(String, nullable=True)  # Links back to the analysis task

    # Order details
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)          # BUY, SELL, STRONG_BUY, STRONG_SELL
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)            # Price at decision time
    value = Column(Float, nullable=False)             # quantity * price
    confidence = Column(Float, nullable=False)        # 0.0 - 1.0
    stop_loss_pct = Column(Float, nullable=True)
    take_profit_pct = Column(Float, nullable=True)
    order_type = Column(String, default="MARKET")     # MARKET or LIMIT
    time_horizon = Column(String, nullable=True)

    # Risk assessment
    risk_score = Column(Float, nullable=True)
    risk_factors = Column(Text, nullable=True)        # JSON array string
    reasoning = Column(String, nullable=True)
    key_factors = Column(Text, nullable=True)         # JSON array string

    # Full decision payload for execution
    decision_json = Column(Text, nullable=False)

    # Idempotency
    idempotency_key = Column(String, unique=True, nullable=False)

    # Status
    status = Column(String, default="PENDING", index=True)  # PENDING, APPROVED, REJECTED, EXPIRED

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False)    # 5 minutes after creation
    resolved_at = Column(DateTime, nullable=True)

    # Result after approval
    order_result_json = Column(Text, nullable=True)

    user = relationship("User")
