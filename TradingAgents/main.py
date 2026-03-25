from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-5-mini"
config["quick_think_llm"] = "gpt-5-mini"
config["max_debate_rounds"] = 1

# Configure data vendors
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

# ── Portfolio Configuration ───────────────────────────────────────────
config["portfolio"] = {
    "initial_cash": 10000.0,
    "max_position_pct": 0.15,
    "max_total_positions": 5,
    "state_file": "./portfolio_state.json",
}

# ── Position Tracker ──────────────────────────────────────────────────
config["position_tracker"] = {
    "trailing_stop_pct": 0.05,
    "max_hold_days": 30,
}

# ── Execution Configuration (Phase 3) ────────────────────────────────
# Option A: Paper Trading (safe, no real money)
config["execution"] = {
    "mode": "paper",                    # Enable paper trading
    "broker": "paper",                  # Use paper broker (local simulation)
    "min_confidence": 0.5,
    "max_daily_loss_pct": 0.05,
    "cooldown_seconds": 60,             # 1 min cooldown for testing
    "commission_pct": 0.001,            # 0.1% commission
    "slippage_pct": 0.0005,             # 0.05% slippage
    "require_confirmation": False,      # Auto-execute in paper mode
}

# Option B: Crypto via CCXT (uncomment to use)
# config["execution"] = {
#     "mode": "paper",                  # Use "live" for real trading
#     "broker": "ccxt",
#     "exchange": "binance",            # Or: bybit, okx, coinbase, etc.
#     "api_key": os.getenv("BINANCE_API_KEY", ""),
#     "api_secret": os.getenv("BINANCE_API_SECRET", ""),
#     "sandbox": True,                  # Use testnet!
#     "quote_currency": "USDT",
#     "min_confidence": 0.6,
#     "require_confirmation": True,
# }

# Option C: US Stocks via Alpaca (uncomment to use)
# config["execution"] = {
#     "mode": "paper",                  # Use "live" for real trading
#     "broker": "alpaca",
#     "api_key": os.getenv("ALPACA_API_KEY", ""),
#     "api_secret": os.getenv("ALPACA_API_SECRET", ""),
#     "min_confidence": 0.6,
#     "require_confirmation": True,
# }

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# ═══════════════════════════════════════════════════════════════════════
# Show initial state
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PORTFOLIO STATE BEFORE TRADING")
print("=" * 60)
print(ta.get_portfolio_summary())

print("\n" + "=" * 60)
print("EXECUTION ENGINE STATUS")
print("=" * 60)
print(ta.get_engine_status())

# ═══════════════════════════════════════════════════════════════════════
# Run analysis + auto-execute trade
# ═══════════════════════════════════════════════════════════════════════
_, decision, order_result = ta.propagate(
    "NVDA", "2024-05-10", auto_execute=True
)

print("\n" + "=" * 60)
print("STRUCTURED TRADE DECISION")
print("=" * 60)
print(decision)

if order_result:
    print("\n" + "=" * 60)
    print("ORDER RESULT")
    print("=" * 60)
    print(f"  Order ID: {order_result.order_id}")
    print(f"  Status:   {order_result.status.value}")
    print(f"  Ticker:   {order_result.ticker}")
    print(f"  Side:     {order_result.side.value}")
    print(f"  Qty:      {order_result.filled_quantity}")
    print(f"  Price:    ${order_result.filled_price:,.4f}" if order_result.filled_price else "  Price:    N/A")
    print(f"  Broker:   {order_result.broker_name}")

# ═══════════════════════════════════════════════════════════════════════
# Post-execution state
# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("PORTFOLIO STATE AFTER TRADING")
print("=" * 60)
print(ta.get_portfolio_summary())

# Check for exit triggers
exits = ta.check_position_exits()
if exits:
    print("\n⚠️  Position exit triggers:")
    for e in exits:
        print(f"  {e['ticker']}: {e['trigger']}")

# Execution engine log
if ta.execution_engine:
    print("\n" + "=" * 60)
    print("EXECUTION LOG")
    print("=" * 60)
    for entry in ta.execution_engine.get_execution_log():
        print(f"  [{entry['action']}] {entry['message']}")

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000)
