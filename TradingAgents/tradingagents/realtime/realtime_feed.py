"""Real-time price monitoring and auto-exit for TradingAgents.

Polls prices via yfinance and triggers stop-loss/take-profit exits.
Runs in a background thread, integrates with StopLossManager and Notifier.

No extra dependencies — uses yfinance (already a project dependency).
"""

import time
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class RealtimeFeed:
    """Real-time price monitor with auto-exit capability.

    Polls prices for all open positions and triggers exits when
    stop-loss, take-profit, or trailing stop conditions are met.

    Usage:
        feed = RealtimeFeed(
            portfolio_manager=pm,
            stop_loss_manager=slm,
            execution_engine=engine,
            notifier=notifier,
            config=config,
        )
        feed.start()
        # ... monitors in background ...
        feed.stop()
    """

    def __init__(
        self,
        portfolio_manager,
        stop_loss_manager=None,
        execution_engine=None,
        notifier=None,
        broker=None,
        config: Optional[dict] = None,
    ):
        """Initialize the realtime feed.

        Args:
            portfolio_manager: PortfolioManager for position tracking
            stop_loss_manager: StopLossManager for exit evaluation
            execution_engine: ExecutionEngine for auto-executing exits
            notifier: Notifier for Telegram alerts
            broker: Optional broker for price fetching (supports futures)
            config: Full application config dict
        """
        self.portfolio = portfolio_manager
        self.stop_loss_manager = stop_loss_manager
        self.execution_engine = execution_engine
        self.notifier = notifier
        self.broker = broker
        self.config = config or {}

        rt_cfg = self.config.get("realtime", {})
        self.poll_interval = rt_cfg.get("poll_interval_seconds", 30)
        self.auto_exit_enabled = rt_cfg.get("auto_exit_enabled", True)

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._poll_count = 0
        self._exits_triggered = 0

    def start(self) -> None:
        """Start the price monitoring thread."""
        if self._running:
            print("[RealtimeFeed] Already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

        print(f"[RealtimeFeed] ✅ Started — poll interval: {self.poll_interval}s")

    def stop(self) -> None:
        """Stop the price monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=self.poll_interval + 5)
            self._thread = None

        print(f"[RealtimeFeed] 🛑 Stopped — {self._poll_count} polls, "
              f"{self._exits_triggered} exits triggered")

    # ── Polling Loop ──────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main polling loop — runs in background thread."""
        while self._running:
            try:
                self._poll_prices()
                self._poll_count += 1
            except Exception as e:
                logger.warning(f"[RealtimeFeed] Poll error: {e}")

            # Sleep in small increments for responsive shutdown
            for _ in range(self.poll_interval):
                if not self._running:
                    break
                time.sleep(1)

    def _poll_prices(self) -> None:
        """Fetch current prices and update portfolio.

        Uses broker.get_current_price() if a broker is available (supports
        futures symbols like BTC/USDT:USDT). Falls back to yfinance for spot.
        """
        positions = self.portfolio.positions
        if not positions:
            return

        tickers = list(positions.keys())
        price_updates: Dict[str, float] = {}

        # Strategy 1: Use broker (supports spot + futures)
        if self.broker:
            for ticker in tickers:
                try:
                    price = self.broker.get_current_price(ticker)
                    if price and price > 0:
                        price_updates[ticker] = float(price)
                except Exception:
                    continue
        else:
            # Strategy 2: Fallback to yfinance (spot only)
            try:
                import yfinance as yf

                for ticker in tickers:
                    try:
                        t = yf.Ticker(ticker)
                        info = t.fast_info
                        price = getattr(info, 'last_price', None)
                        if price is None:
                            price = getattr(info, 'previous_close', None)
                        if price and price > 0:
                            price_updates[ticker] = float(price)
                    except Exception:
                        continue
            except ImportError:
                logger.warning("[RealtimeFeed] yfinance not available for price polling")
            except Exception as e:
                logger.warning(f"[RealtimeFeed] Price fetch error: {e}")

        if price_updates:
            # Update portfolio with new prices
            self.portfolio.update_prices(price_updates)

            # Check for exits
            if self.auto_exit_enabled:
                self._check_exits(price_updates)

    def _check_exits(self, price_updates: Dict[str, float]) -> None:
        """Check all positions for exit triggers.

        Args:
            price_updates: Dict of ticker -> current price
        """
        # Check StopLossManager signals if available
        if self.stop_loss_manager:
            signals = self.stop_loss_manager.check_exits(
                current_prices=price_updates,
            )

            for sig in signals:
                self._handle_exit(
                    ticker=sig.ticker,
                    reason=sig.reason.value,
                    current_price=sig.current_price,
                )
            return

        # Fallback: check portfolio's own SL/TP
        triggered = self.portfolio.check_stop_loss_take_profit()
        for trig in triggered:
            self._handle_exit(
                ticker=trig["ticker"],
                reason=trig["trigger"],
                current_price=trig.get("current_price", 0),
            )

    def _handle_exit(self, ticker: str, reason: str, current_price: float) -> None:
        """Handle an exit trigger — execute and notify.

        Args:
            ticker: Ticker that triggered exit
            reason: Exit reason
            current_price: Current market price
        """
        self._exits_triggered += 1
        print(f"[RealtimeFeed] ⚠️ Exit trigger: {ticker} — {reason} @ ${current_price:,.4f}")

        # Auto-execute exit via execution engine
        if self.execution_engine and self.auto_exit_enabled:
            try:
                self.execution_engine.process_exit_signals()
            except Exception as e:
                logger.warning(f"[RealtimeFeed] Auto-exit failed for {ticker}: {e}")

        # Calculate loss for notification
        position = self.portfolio.positions.get(ticker)
        loss_amount = 0.0
        if position:
            loss_amount = position.unrealized_pnl

        # Send notification
        if self.notifier:
            self.notifier.send_stop_loss_alert(
                ticker=ticker,
                exit_price=current_price,
                loss_amount=loss_amount,
                reason=reason,
            )

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get realtime feed status."""
        return {
            "running": self._running,
            "poll_interval_seconds": self.poll_interval,
            "poll_count": self._poll_count,
            "exits_triggered": self._exits_triggered,
            "monitoring_positions": len(self.portfolio.positions),
            "auto_exit_enabled": self.auto_exit_enabled,
        }
