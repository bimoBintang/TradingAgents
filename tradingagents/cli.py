"""CLI runner for TradingAgents.

Provides a rich terminal interface for all trading modes:
  --analyze NVDA       Single analysis run
  --paper              Start paper trading session
  --live               Start live trading (with confirmation)
  --schedule 60        Autonomous scheduled runs (interval in minutes)
  --watchlist NVDA,AAPL  Multi-ticker watchlist
  --status             Show portfolio status
  --journal            Show trade journal summary
  --export FILE        Export trades to CSV

Requires: rich>=13.0
"""

import argparse
import os
import sys
import json
import time
import signal
from datetime import datetime
from typing import Optional

# Lazy imports for optional dependencies
_rich_available = True
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
except ImportError:
    _rich_available = False


def _get_console():
    """Get Rich console, with fallback."""
    if _rich_available:
        return Console()
    return None


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tradingagents",
        description="🤖 TradingAgents — Multi-Agent LLM Trading Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tradingagents.cli --analyze NVDA
  python -m tradingagents.cli --paper --watchlist NVDA,AAPL,TSLA --schedule 60
  python -m tradingagents.cli --status
  python -m tradingagents.cli --journal
  python -m tradingagents.cli --export trades.csv
        """,
    )

    # Analysis modes
    parser.add_argument("--analyze", "-a", metavar="TICKER",
                        help="Run single analysis for a ticker")
    parser.add_argument("--paper", action="store_true",
                        help="Start paper trading session")
    parser.add_argument("--live", action="store_true",
                        help="Start live trading session (requires confirmation)")

    # Scheduler
    parser.add_argument("--schedule", "-s", type=int, metavar="MINUTES",
                        help="Run scheduled analysis every N minutes")
    parser.add_argument("--watchlist", "-w", metavar="TICKERS",
                        help="Comma-separated list of tickers (default: NVDA)")

    # Info commands
    parser.add_argument("--status", action="store_true",
                        help="Show current portfolio status")
    parser.add_argument("--journal", action="store_true",
                        help="Show trade journal summary")
    parser.add_argument("--export", "-e", metavar="FILE",
                        help="Export trades to CSV file")

    # Notifications
    parser.add_argument("--test-notify", action="store_true",
                        help="Send a test notification to verify Telegram setup")

    # Config
    parser.add_argument("--config", "-c", metavar="FILE",
                        help="Path to config JSON file")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug mode")

    return parser


def _load_config(config_path: Optional[str] = None) -> dict:
    """Load configuration from file or defaults."""
    from tradingagents.default_config import DEFAULT_CONFIG
    config = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        with open(config_path, "r") as f:
            user_config = json.load(f)
        config.update(user_config)
        print(f"[CLI] Loaded config from {config_path}")

    return config


def _print_banner(console):
    """Print the TradingAgents banner."""
    if console and _rich_available:
        banner = Text()
        banner.append("🤖 TradingAgents", style="bold cyan")
        banner.append(" — Multi-Agent LLM Trading Framework\n", style="dim")
        banner.append(f"   Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}", style="dim")
        console.print(Panel(banner, border_style="cyan", box=box.DOUBLE))
    else:
        print("=" * 50)
        print("🤖 TradingAgents — Multi-Agent LLM Trading Framework")
        print(f"   Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 50)


def _print_portfolio_status(graph, console):
    """Print portfolio status as a rich table."""
    try:
        pm = graph.portfolio_manager
        ps = pm.get_portfolio_state()

        if console and _rich_available:
            table = Table(title="📊 Portfolio Status", box=box.ROUNDED, border_style="cyan")
            table.add_column("Metric", style="bold")
            table.add_column("Value", justify="right")

            table.add_row("Cash Balance", f"${ps.cash_balance:,.2f}")
            table.add_row("Total Equity", f"${ps.total_equity:,.2f}")
            table.add_row("Open Positions", str(len(ps.open_positions or [])))
            table.add_row("Daily P&L", f"${ps.daily_pnl:,.2f}" if ps.daily_pnl else "$0.00")
            table.add_row("Total P&L", f"${ps.total_pnl:,.2f}")
            table.add_row("Win Rate", f"{ps.win_rate:.0%}")
            table.add_row("Max Drawdown", f"{ps.max_drawdown_pct:.1%}")
            table.add_row("Total Trades", str(ps.total_trades))
            console.print(table)

            # Open positions
            if ps.open_positions:
                pos_table = Table(title="📌 Open Positions", box=box.SIMPLE, border_style="yellow")
                pos_table.add_column("Ticker", style="bold")
                pos_table.add_column("Side")
                pos_table.add_column("Qty", justify="right")
                pos_table.add_column("Entry", justify="right")
                pos_table.add_column("Current", justify="right")
                pos_table.add_column("P&L", justify="right")

                for p in ps.open_positions:
                    pnl = p.unrealized_pnl
                    pnl_style = "green" if pnl >= 0 else "red"
                    pos_table.add_row(
                        p.ticker,
                        p.side.value if hasattr(p.side, 'value') else str(p.side),
                        f"{p.quantity}",
                        f"${p.entry_price:,.2f}",
                        f"${p.current_price:,.2f}",
                        Text(f"${pnl:,.2f}", style=pnl_style),
                    )
                console.print(pos_table)
        else:
            print(pm.get_portfolio_context_string())

    except Exception as e:
        print(f"[CLI] Error getting portfolio status: {e}")


def _print_journal_report(graph, console):
    """Print trade journal performance report."""
    try:
        if not hasattr(graph, 'journal') or not graph.journal:
            print("[CLI] No trade journal available (storage disabled?)")
            return

        report = graph.journal.get_performance_report()
        if not report or report.get("total_trades", 0) == 0:
            print("[CLI] No trades recorded yet")
            return

        if console and _rich_available:
            table = Table(title="📈 Performance Report", box=box.ROUNDED, border_style="green")
            table.add_column("Metric", style="bold")
            table.add_column("Value", justify="right")

            table.add_row("Total Trades", str(report.get("total_trades", 0)))
            table.add_row("Win Rate", f"{report.get('win_rate', 0):.0%}")
            table.add_row("Profit Factor", f"{report.get('profit_factor', 0):.2f}")
            table.add_row("Sharpe Ratio", f"{report.get('sharpe_ratio', 0):.2f}")
            table.add_row("Max Drawdown", f"{report.get('max_drawdown', 0):.1%}")
            table.add_row("Avg P&L", f"${report.get('avg_pnl', 0):,.2f}")
            table.add_row("Best Trade", f"${report.get('best_trade', 0):,.2f}")
            table.add_row("Worst Trade", f"${report.get('worst_trade', 0):,.2f}")
            console.print(table)

            # Rejection stats
            rej = graph.journal.get_rejection_stats()
            if rej:
                rej_table = Table(title="⛔ Rejection Stats", box=box.SIMPLE, border_style="red")
                rej_table.add_column("Reason", style="bold")
                rej_table.add_column("Count", justify="right")
                for code, count in rej.items():
                    rej_table.add_row(code, str(count))
                console.print(rej_table)
        else:
            print("=== Performance Report ===")
            for k, v in report.items():
                print(f"  {k}: {v}")

    except Exception as e:
        print(f"[CLI] Error getting journal report: {e}")


def run_cli(args=None) -> None:
    """Main CLI entry point."""
    parser = create_parser()
    parsed = parser.parse_args(args)

    console = _get_console()
    _print_banner(console)

    # Load config
    config = _load_config(parsed.config)

    # Apply CLI overrides
    if parsed.paper:
        config.setdefault("execution", {})["mode"] = "paper"
        config["execution"]["broker"] = "paper"
        config["execution"]["require_confirmation"] = False

    if parsed.live:
        config.setdefault("execution", {})["mode"] = "live"
        config["execution"]["require_confirmation"] = True

    if parsed.watchlist:
        tickers = [t.strip().upper() for t in parsed.watchlist.split(",")]
        config.setdefault("scheduler", {})["watchlist"] = tickers

    if parsed.schedule:
        config.setdefault("scheduler", {})["interval_minutes"] = parsed.schedule
        config["scheduler"]["enabled"] = True

    if parsed.debug:
        config["debug"] = True

    # ── Simple commands that don't need full graph ────────────────────

    if parsed.export:
        from tradingagents.storage.database import Database
        storage_cfg = config.get("storage", {})
        if storage_cfg.get("enabled"):
            db = Database(storage_cfg.get("db_path", "~/.tradingagents/trading.db"))
            from tradingagents.storage.trade_journal import TradeJournal
            journal = TradeJournal(db, "export-session")
            journal.export_csv(parsed.export)
            db.close()
        else:
            print("[CLI] Storage is disabled. No data to export.")
        return

    # ── Commands needing the full graph ───────────────────────────────

    # Initialize the graph
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.notifications.notifier import Notifier

    ta = TradingAgentsGraph(
        debug=parsed.debug,
        config=config,
    )

    # Create notifier
    notifier = Notifier(config)

    # Test notification
    if parsed.test_notify:
        if notifier.enabled:
            success = notifier.test_connection()
            print(f"[CLI] Telegram test: {'✅ Sent' if success else '❌ Failed'}")
        else:
            print("[CLI] Notifications disabled. Set notifications.enabled=True")
        return

    # Status
    if parsed.status:
        _print_portfolio_status(ta, console)
        return

    # Journal
    if parsed.journal:
        _print_journal_report(ta, console)
        return

    # ── Analysis Mode ─────────────────────────────────────────────────

    if parsed.analyze:
        ticker = parsed.analyze.upper()
        trade_date = datetime.now().strftime("%Y-%m-%d")

        if console and _rich_available:
            console.print(f"\n🔍 Analyzing [bold cyan]{ticker}[/] ({trade_date})...")
        else:
            print(f"\n🔍 Analyzing {ticker} ({trade_date})...")

        auto_execute = config.get("execution", {}).get("mode", "disabled") != "disabled"
        _, decision, order_result = ta.propagate(ticker, trade_date, auto_execute=auto_execute)

        if order_result:
            print(f"\n✅ Order: {order_result.side.value} {order_result.filled_quantity} "
                  f"{ticker} @ ${order_result.filled_price:,.4f}")
            if notifier.enabled:
                notifier.send_trade_alert(order_result, ticker)
        else:
            print(f"\n📋 Decision: {decision}")

        _print_portfolio_status(ta, console)
        return

    # ── Scheduled Mode ────────────────────────────────────────────────

    if parsed.schedule or parsed.paper or parsed.live:
        from tradingagents.scheduler.scheduler import TradingScheduler
        from tradingagents.realtime.realtime_feed import RealtimeFeed

        # Scheduler
        sched_config = config.get("scheduler", {})
        if not sched_config.get("watchlist"):
            sched_config["watchlist"] = ["NVDA"]

        scheduler = TradingScheduler(
            graph=ta,
            notifier=notifier,
            config=config,
        )

        # Realtime feed
        rt_config = config.get("realtime", {})
        realtime_feed = None
        if rt_config.get("enabled", False):
            realtime_feed = RealtimeFeed(
                portfolio_manager=ta.portfolio_manager,
                stop_loss_manager=getattr(ta, 'stop_loss_manager', None),
                execution_engine=ta.execution_engine,
                notifier=notifier,
                config=config,
            )
            realtime_feed.start()

        scheduler.start()

        # Block until CTRL+C
        try:
            if console and _rich_available:
                console.print("\n[dim]Press Ctrl+C to stop...[/]")
            else:
                print("\nPress Ctrl+C to stop...")

            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.stop()
            if realtime_feed:
                realtime_feed.stop()
            _print_portfolio_status(ta, console)

        return

    # No command specified
    parser.print_help()


if __name__ == "__main__":
    run_cli()
