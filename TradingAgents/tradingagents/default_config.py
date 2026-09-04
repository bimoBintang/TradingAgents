import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "anthropic",  # Default fallback provider
    
    "deep_think_llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-6",
    
    "smart_think_llm_provider": "anthropic",
    "smart_think_llm": "claude-sonnet-4-6",
    
    # NOTE (2026-08-25): was "google"/"gemini-3.1-pro" — that requires
    # Google Application Default Credentials (gcloud ADC), not just
    # GOOGLE_API_KEY, and .env only has GOOGLE_API_KEY (empty). Without
    # ADC set up, TradingAgentsGraph init fails entirely and the whole
    # server (API + MCP) runs in degraded mode. Anthropic is used
    # instead since ANTHROPIC_API_KEY is already configured in .env.
    # Switch back to google once ADC is set up (see
    # https://cloud.google.com/docs/authentication/external/set-up-adc),
    # or point GOOGLE_API_KEY-based auth explicitly if that becomes supported.
    "fast_think_llm_provider": "anthropic",
    "fast_think_llm": "claude-haiku-4-5",
    
    "backend_url": "https://api.anthropic.com",
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    # ── Token Compression (Settings > AI Language Models) ─────────────
    # "Compress tool output (RTK)": wraps every tool on every ToolNode
    # (get_stock_data, get_news, get_indicators, financial statements,
    # ...) so large/repetitive text results get truncated+deduped before
    # they enter agent context — same idea as compressing git/grep/ls/
    # tree/log output in a coding agent, applied to this app's own
    # data-fetching tools. See tradingagents/agents/utils/tool_compression.py.
    "compress_tool_output": False,
    # "Compress LLM output (Caveman)": appends a terse-style directive to
    # the shared STRICT_SYSTEM_PREAMBLE used by market/quant/fundamentals/
    # news analysts, the synthesizer, bull/bear researchers, the
    # aggressive/conservative debators, and the risk manager — cutting
    # output tokens by favoring short bullet points over prose. See
    # tradingagents/agents/utils/prompt_blocks.py's get_strict_system_preamble().
    "compress_llm_output": False,
    # Debate and discussion settings
    "max_debate_rounds": 2,
    "max_risk_discuss_rounds": 2,
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
        # Example: "get_news": "mcp",  # Route this one tool through an external MCP server instead
    },
    # ── MCP Client (Fase 6) — consume an external MCP server as a data vendor ──
    # Generic infrastructure, disabled by default: point it at any MCP
    # server exposing get_stock_data/get_indicators/etc.-shaped tools
    # (see tradingagents/dataflows/mcp_client.py), then select it like
    # any other vendor via data_vendors/tool_vendors above (vendor name
    # "mcp"), or let route_to_vendor()'s fallback chain try it last.
    "mcp_client": {
        "enabled": False,
        "transport": "stdio",           # "stdio" | "streamable-http"
        "command": None,                # stdio: e.g. "npx"
        "args": [],                     # stdio: e.g. ["-y", "some-mcp-data-server"]
        "env": None,                    # stdio: extra env vars for the subprocess
        "url": None,                    # streamable-http: server URL
        "headers": {},                  # streamable-http: e.g. auth headers
        "tool_map": {
            # our tool name -> the external server's tool name, if different
            "get_stock_data": "get_stock_data",
            "get_indicators": "get_indicators",
            "get_fundamentals": "get_fundamentals",
            "get_balance_sheet": "get_balance_sheet",
            "get_cashflow": "get_cashflow",
            "get_income_statement": "get_income_statement",
            "get_news": "get_news",
            "get_global_news": "get_global_news",
            "get_insider_transactions": "get_insider_transactions",
        },
    },
    # ── Portfolio Configuration (Phase 2) ─────────────────────────────
    "portfolio": {
        "initial_cash": 10000.0,             # Starting cash balance
        "max_position_pct": 0.10,            # Max 10% of portfolio per position
        "max_total_positions": 10,            # Max concurrent open positions
        "state_file": None,                  # Path to persist portfolio (JSON), None = in-memory only
        # ── Fractional Kelly position sizing ──────────────────────────
        # Caps allocation by the edge actually demonstrated in this
        # portfolio's own closed trades. Off by default and a no-op until
        # MIN_TRADES_FOR_EDGE (30) real trades exist — before that there
        # is nothing to measure. It can only SHRINK an agent's requested
        # size, never grow it. See tradingagents/execution/position_sizing.py.
        "kelly_enabled": False,
        "kelly_multiplier": 0.25,            # 0.25 = quarter-Kelly, 0.5 = half-Kelly
    },
    # ── MCP Server Configuration ──────────────────────────────────────
    # Which account mcp_server/server.py acts as when Claude Desktop/Code
    # calls read_portfolio/list_recent_trades/run_analysis. The MCP
    # server has no HTTP request/JWT to authenticate with (it's a local
    # subprocess), so identity is fixed here instead of per-request.
    "mcp": {
        "user_email": "",                    # Set via Settings > MCP Server, or TRADINGAGENTS_MCP_USER_EMAIL env var
    },
    # ── Position Tracker Configuration (Phase 2) ─────────────────────
    "position_tracker": {
        "trailing_stop_pct": 0.0,            # Trailing stop % (0.0 = disabled, e.g., 0.05 = 5%)
        "max_hold_days": 0,                  # Max days to hold (0 = unlimited)
    },
    # ── Execution Configuration (Phase 3: Broker Integration) ──────────
    "execution": {
        "mode": "paper",                     # disabled | paper | live
        "broker": "paper",                   # paper | ccxt | alpaca
        # Broker-specific settings
        "exchange": None,                    # None until user selects: binance, bybit, okx, bitget, etc.
        "api_key": "",                       # Set by user via Dashboard
        "api_secret": "",                    # Set by user via Dashboard
        "password": "",                      # Some exchanges require passphrase (e.g., OKX)
        "sandbox": False,                    # False = REAL account
        "quote_currency": "USDT",            # Default quote currency for CCXT
        # Futures-specific settings
        "market_type": "spot",               # "spot" | "future"
        "leverage": 1,                       # Default leverage (1 = spot-equivalent)
        "margin_type": "isolated",           # "isolated" | "cross"
        "max_leverage": 10,                  # Hard cap leverage (safety)
        # Trade execution parameters
        "min_confidence": 0.5,               # Minimum confidence to execute
        "max_daily_loss_pct": 0.05,          # Kill switch: stop if daily loss > 5%
        "cooldown_seconds": 300,             # Min seconds between trades on same ticker
        "balance_sync_interval_seconds": 30, # How often api/services/balance_sync.py polls the real broker balance
        "commission_pct": 0.001,             # Simulated commission for paper broker (0.1%)
        "slippage_pct": 0.0005,              # Simulated slippage for paper broker (0.05%)
        "require_confirmation": True,        # Manual confirm before live trades
        # How long a queued order stays approvable. A trade thesis decays:
        # approving a signal generated hours ago executes on a market that
        # no longer resembles the one that was analyzed. Expired orders are
        # never executable — they must be re-analyzed instead.
        "pending_order_ttl_seconds": 900,    # 15 minutes
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
        # Scopes durable risk state (kill switch, loss streak, PnL window)
        # inside the shared database file. The multi-tenant API overrides
        # this per user in api/user_context.py — leaving every account on
        # "default" would give the whole platform ONE shared kill switch.
        "account_id": "default",
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
    # ── Order Flow / Market Microstructure ─────────────────────────────
    "order_flow": {
        "enabled": False,                                # Disabled by default (backward-compatible)
        "obi_execute_threshold": 0.15,                   # OBI ≥ this → immediate execution
        "obi_block_threshold": -0.30,                    # OBI ≤ this → block execution
        "order_book_depth": 20,                          # Levels of order book to analyze
        "max_wait_seconds": 60,                          # Max wait for favorable OBI
        "poll_interval_seconds": 5,                      # OBI re-check interval during wait
        "wall_detection_usd": 100000,                    # Threshold (USD) for wall detection
    },
}

