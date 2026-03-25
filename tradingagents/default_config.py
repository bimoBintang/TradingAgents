import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-sonnet-4-6",
    "quick_think_llm": "claude-haiku-4-5",
    "backend_url": "https://api.anthropic.com",
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Phase 9: Advanced specialist agents
    "enable_execution_optimizer": True,
    "onchain_enabled_patterns": ["BTC", "ETH", "SOL", "DOGE", "XRP", "-USD", "-USDT"],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # ── Portfolio Configuration (Phase 2) ─────────────────────────────
    "portfolio": {
        "initial_cash": 10000.0,             # Starting cash balance
        "max_position_pct": 0.10,            # Max 10% of portfolio per position
        "max_total_positions": 10,            # Max concurrent open positions
        "state_file": None,                  # Path to persist portfolio (JSON), None = in-memory only
    },
    # ── Position Tracker Configuration (Phase 2) ─────────────────────
    "position_tracker": {
        "trailing_stop_pct": 0.0,            # Trailing stop % (0.0 = disabled, e.g., 0.05 = 5%)
        "max_hold_days": 0,                  # Max days to hold (0 = unlimited)
    },
    # ── Execution Configuration (Phase 3: Broker Integration) ──────────
    "execution": {
        "mode": "live",                       # disabled | paper | live
        "broker": "ccxt",                    # paper | ccxt | alpaca
        # Broker-specific settings
        "exchange": "binance",               # For CCXT: binance, bybit, okx, coinbase, etc.
        "api_key": "",                       # Loaded from BINANCE_API_KEY env var
        "api_secret": "",                    # Loaded from BINANCE_API_SECRET env var
        "password": "",                      # Some exchanges require passphrase (e.g., OKX)
        "sandbox": False,                    # False = REAL account
        "quote_currency": "USDT",            # Default quote currency for CCXT
        # Trade execution parameters
        "min_confidence": 0.5,               # Minimum confidence to execute
        "max_daily_loss_pct": 0.05,          # Kill switch: stop if daily loss > 5%
        "cooldown_seconds": 300,             # Min seconds between trades on same ticker
        "commission_pct": 0.001,             # Simulated commission for paper broker (0.1%)
        "slippage_pct": 0.0005,              # Simulated slippage for paper broker (0.05%)
        "require_confirmation": True,        # Manual confirm before live trades
        "atr_timeframe": "1h",                   # OHLCV timeframe for ATR calculation via CCXT
        # Retry settings for transient network errors
        "retry_max_attempts": 3,             # Max retry attempts (0 = no retries)
        "retry_base_delay": 1.0,             # Initial delay in seconds
        "retry_max_delay": 30.0,             # Maximum delay cap in seconds
        "retry_backoff_factor": 2.0,         # Exponential backoff multiplier
    },
    # ── Risk Controls Configuration (Phase 4) ─────────────────────────
    "risk_controls": {
        "max_daily_loss_pct": 0.05,              # Halt trading if daily loss > 5%
        "max_weekly_loss_pct": 0.10,             # Halt trading if weekly loss > 10%
        "max_position_pct": 0.10,                # Max 10% of equity per single position
        "max_concurrent_positions": 5,           # Max open positions at once
        "kill_switch_enabled": True,             # Enable automatic kill switch on drawdown breach
        "consecutive_loss_limit": 3,             # Cooldown after N consecutive losing trades
        "cooldown_seconds": 1800,                # 30 min cooldown after consecutive losses
        "atr_multiplier": 2.0,                   # ATR-based stop distance multiplier
        "trailing_stop_pct": 0.05,               # 5% trailing stop from high watermark
        "max_hold_hours": 72,                    # Force exit if held > 72h with no meaningful move
    },
    # ── Storage Configuration (Phase 5: Persistent Memory) ────────────
    "storage": {
        "enabled": True,                             # Enable SQLite persistence
        "db_path": "~/.tradingagents/trading.db",    # SQLite database file
        "snapshot_interval_minutes": 30,             # Deferred to Phase 6 scheduler
        "max_memory_items_per_agent": 500,           # Max BM25 pairs per agent
        "max_reflections_loaded": 20,                # Per ticker per session
        "decisions_retention_days": 90,              # Purge decisions older than N days
        "reflections_retention_days": 365,           # Purge reflections older than N days
        "risk_free_rate_annual": 0.05,               # For Sharpe ratio calculation
        "export_csv_on_exit": False,                 # Auto-export trades CSV on shutdown
    },
    # ── Notifications Configuration (Phase 6) ─────────────────────────
    "notifications": {
        "enabled": False,                                # Enable Telegram notifications
        "telegram_bot_token": "",                        # Bot token from @BotFather
        "telegram_chat_id": "",                          # Chat ID (use @userinfobot)
        "rate_limit_per_minute": 30,                     # Max alerts per minute
        "alert_on_trade": True,                          # Notify on trade execution
        "alert_on_rejection": True,                      # Notify on trade rejection
        "alert_on_stop_loss": True,                      # Notify on stop-loss hit
        "alert_on_kill_switch": True,                    # Notify on kill switch activation
        "daily_summary_enabled": True,                   # Send daily P&L summary
        "daily_summary_hour": 16,                        # Hour (EST) to send daily summary
    },
    # ── Scheduler Configuration (Phase 6) ─────────────────────────────
    "scheduler": {
        "enabled": False,                                # Enable autonomous scheduler
        "interval_minutes": 60,                          # Analysis interval in minutes
        "watchlist": ["NVDA"],                           # Default watchlist
        "market_hours_only": True,                       # Skip analysis outside market hours
        "market_open_hour": 9,                           # Market open hour (EST)
        "market_close_hour": 16,                         # Market close hour (EST)
        "crypto_24_7": True,                             # Crypto tickers run 24/7
        "max_trades_per_day": 10,                        # Max trades per trading day
        "analysis_timeout_seconds": 300,                 # Timeout for single analysis
        "auto_execute": True,                            # Auto-execute approved decisions
    },
    # ── Realtime Feed Configuration (Phase 6) ─────────────────────────
    "realtime": {
        "enabled": False,                                # Enable realtime price monitoring
        "poll_interval_seconds": 30,                     # Price polling interval
        "auto_exit_enabled": True,                       # Auto-trigger stop-loss exits
    },
}

