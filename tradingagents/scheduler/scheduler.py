"""Autonomous trading scheduler for TradingAgents.

Runs analysis cycles on configurable intervals using APScheduler.
Supports multi-ticker watchlists, market hours awareness,
and graceful shutdown via signal handlers.

Requires: apscheduler>=3.11.0
"""

import signal
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Lazy import APScheduler to make it optional
_APScheduler = None


def _get_scheduler_class():
    """Lazy import APScheduler."""
    global _APScheduler
    if _APScheduler is None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            _APScheduler = BackgroundScheduler
        except ImportError:
            raise ImportError(
                "APScheduler is required for the trading scheduler. "
                "Install it: pip install apscheduler>=3.11.0"
            )
    return _APScheduler


class TradingScheduler:
    """Autonomous trading scheduler.

    Runs analysis cycles on configurable intervals, scans multiple tickers,
    respects market hours, and integrates with the full trading pipeline.

    Usage:
        scheduler = TradingScheduler(graph=ta, notifier=notifier, config=config)
        scheduler.start()
        # ... runs in background ...
        scheduler.stop()
    """

    def __init__(
        self,
        graph,
        notifier=None,
        config: Optional[dict] = None,
    ):
        """Initialize the trading scheduler.

        Args:
            graph: TradingAgentsGraph instance
            notifier: Optional Notifier for alerts
            config: Full application config dict
        """
        self.graph = graph
        self.notifier = notifier
        self.config = config or {}

        sched_cfg = self.config.get("scheduler", {})
        self.interval_minutes = sched_cfg.get("interval_minutes", 60)
        self.watchlist: List[str] = list(sched_cfg.get("watchlist", ["NVDA"]))
        self.market_hours_only = sched_cfg.get("market_hours_only", True)
        self.market_open_hour = sched_cfg.get("market_open_hour", 9)
        self.market_close_hour = sched_cfg.get("market_close_hour", 16)
        self.crypto_24_7 = sched_cfg.get("crypto_24_7", True)
        self.max_trades_per_day = sched_cfg.get("max_trades_per_day", 10)
        self.analysis_timeout = sched_cfg.get("analysis_timeout_seconds", 300)
        self.auto_execute = sched_cfg.get("auto_execute", True)

        # State tracking
        self._scheduler = None
        self._running = False
        self._trades_today = 0
        self._last_reset_date = None
        self._cycle_count = 0
        self._lock = threading.Lock()

        # Register signal handlers for graceful shutdown
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._original_sigterm = signal.getsignal(signal.SIGTERM)

    def start(self) -> None:
        """Start the scheduler.

        Begins running analysis cycles at the configured interval.
        """
        if self._running:
            print("[Scheduler] Already running")
            return

        SchedulerClass = _get_scheduler_class()
        self._scheduler = SchedulerClass()

        # Add the main job
        self._scheduler.add_job(
            self._run_all_tickers,
            "interval",
            minutes=self.interval_minutes,
            id="trading_cycle",
            max_instances=1,
            misfire_grace_time=60,
        )

        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._running = True
        self._scheduler.start()

        print(f"[Scheduler] ✅ Started — interval: {self.interval_minutes}min, "
              f"watchlist: {self.watchlist}")

        if self.notifier:
            self.notifier.send_custom(
                "Scheduler Started",
                f"📊 Interval: {self.interval_minutes}min\n"
                f"📋 Watchlist: {', '.join(self.watchlist)}\n"
                f"🔁 Auto-execute: {'On' if self.auto_execute else 'Off'}"
            )

        # Run first cycle immediately
        threading.Thread(target=self._run_all_tickers, daemon=True).start()

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running:
            return

        self._running = False

        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        # Restore original signal handlers
        signal.signal(signal.SIGINT, self._original_sigint)
        signal.signal(signal.SIGTERM, self._original_sigterm)

        print(f"[Scheduler] 🛑 Stopped after {self._cycle_count} cycles")

        if self.notifier:
            self.notifier.send_custom(
                "Scheduler Stopped",
                f"🛑 Cycles completed: {self._cycle_count}\n"
                f"📊 Trades today: {self._trades_today}"
            )

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the watchlist."""
        if ticker not in self.watchlist:
            self.watchlist.append(ticker)
            print(f"[Scheduler] Added {ticker} to watchlist")

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the watchlist."""
        if ticker in self.watchlist:
            self.watchlist.remove(ticker)
            print(f"[Scheduler] Removed {ticker} from watchlist")

    # ── Cycle Execution ───────────────────────────────────────────────

    def _run_all_tickers(self) -> None:
        """Run analysis for all tickers in the watchlist."""
        if not self._running:
            return

        self._reset_daily_counters()
        self._cycle_count += 1

        print(f"\n[Scheduler] === Cycle #{self._cycle_count} === "
              f"({datetime.utcnow().strftime('%H:%M UTC')})")

        for ticker in list(self.watchlist):
            if not self._running:
                break

            if self._trades_today >= self.max_trades_per_day:
                print(f"[Scheduler] Max trades/day ({self.max_trades_per_day}) reached, skipping remaining")
                break

            if not self._is_market_open(ticker):
                print(f"[Scheduler] Market closed for {ticker}, skipping")
                continue

            self._run_cycle(ticker)

        # Periodic portfolio snapshot (Phase 5 integration)
        if hasattr(self.graph, 'journal') and self.graph.journal:
            try:
                portfolio_state = self.graph.portfolio_manager.get_portfolio_state()
                self.graph.journal.snapshot_portfolio(portfolio_state)
            except Exception:
                pass

    def _run_cycle(self, ticker: str) -> None:
        """Run a single analysis + optional execution cycle.

        Args:
            ticker: Ticker symbol to analyze
        """
        try:
            trade_date = datetime.now().strftime("%Y-%m-%d")
            print(f"[Scheduler] Analyzing {ticker} ({trade_date})...")

            _, decision, order_result = self.graph.propagate(
                ticker, trade_date, auto_execute=self.auto_execute
            )

            if order_result:
                self._trades_today += 1
                print(f"[Scheduler] ✅ {ticker}: {order_result.side.value} "
                      f"{order_result.filled_quantity} @ ${order_result.filled_price:,.4f}")

                # Send notification
                if self.notifier:
                    self.notifier.send_trade_alert(order_result, ticker)
            else:
                action = "HOLD"
                if hasattr(decision, 'action'):
                    action = getattr(decision.action, 'value', str(decision.action))
                elif isinstance(decision, str):
                    # Parse from JSON string
                    import json
                    try:
                        d = json.loads(decision)
                        action = d.get("action", "HOLD")
                    except (json.JSONDecodeError, TypeError):
                        action = decision[:20] if decision else "HOLD"

                print(f"[Scheduler] {ticker}: {action} (no trade)")

        except Exception as e:
            logger.error(f"[Scheduler] Error analyzing {ticker}: {e}")
            if self.notifier:
                self.notifier.send_custom(
                    f"Analysis Error: {ticker}",
                    f"⚠️ {str(e)[:200]}"
                )

    # ── Market Hours ──────────────────────────────────────────────────

    def _is_market_open(self, ticker: str) -> bool:
        """Check if the market is currently open for this ticker.

        Args:
            ticker: Ticker symbol

        Returns:
            True if market is open
        """
        if not self.market_hours_only:
            return True

        # Crypto is 24/7
        is_crypto = "/" in ticker or ticker.endswith("USDT") or ticker.endswith("USD")
        if is_crypto and self.crypto_24_7:
            return True

        now = datetime.utcnow()

        # Skip weekends (UTC) — approximate for US stocks
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # EST = UTC - 5 (approximate, ignores DST)
        est_hour = (now.hour - 5) % 24
        return self.market_open_hour <= est_hour < self.market_close_hour

    # ── Helpers ───────────────────────────────────────────────────────

    def _reset_daily_counters(self) -> None:
        """Reset daily trade counter at the start of a new day."""
        today = datetime.utcnow().date()
        if self._last_reset_date != today:
            self._trades_today = 0
            self._last_reset_date = today

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        print(f"\n[Scheduler] Signal {signum} received, shutting down...")
        self.stop()

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "running": self._running,
            "interval_minutes": self.interval_minutes,
            "watchlist": list(self.watchlist),
            "cycles_completed": self._cycle_count,
            "trades_today": self._trades_today,
            "max_trades_per_day": self.max_trades_per_day,
            "market_hours_only": self.market_hours_only,
            "auto_execute": self.auto_execute,
        }
