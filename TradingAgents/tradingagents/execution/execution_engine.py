"""Execution engine that orchestrates trade decisions to broker execution.

Bridges the gap between agent TradeDecisions and actual broker order placement.
Includes pre-flight safety checks, RiskController gate, post-execution portfolio
updates, idempotency protection, and logging.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set

logger = logging.getLogger(__name__)

from tradingagents.execution.order_models import (
    TradeAction,
    TradeDecision,
    RiskAssessment,
    OrderSide,
    OrderType,
    OrderResult,
    OrderStatus,
)
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.position_tracker import PositionTracker
from tradingagents.execution.brokers.broker_base import BaseBroker
from tradingagents.execution.stop_loss_manager import StopLossManager, ExitSignal


class ExecutionEngine:
    """Orchestrates the flow from TradeDecision → Broker order → Portfolio update.

    Acts as the central coordinator between:
    - Agent decisions (TradeDecision / RiskAssessment)
    - RiskController (Phase 4 pre-execution gate)
    - Risk checks (pre-flight validation)
    - Broker execution (order placement)
    - Portfolio updates (position tracking)

    Safety Features:
    - RiskController gate (drawdown, correlation, ATR sizing, kill switch)
    - Idempotency keys to prevent double orders on retry
    - Minimum confidence threshold
    - Maximum position size limits
    - Cooldown period between trades
    - Daily loss limit (kill switch)
    - Optional manual confirmation for live trading
    """

    def __init__(
        self,
        broker: BaseBroker,
        portfolio_manager: PortfolioManager,
        position_tracker: Optional[PositionTracker] = None,
        risk_controller: Optional["RiskController"] = None,
        stop_loss_manager: Optional[StopLossManager] = None,
        journal = None,
        notifier = None,
        min_confidence: float = 0.5,
        max_daily_loss_pct: float = 0.05,
        cooldown_seconds: int = 300,
        require_confirmation: bool = True,
        atr_timeframe: str = "1h",
    ):
        """Initialize the execution engine.

        Args:
            broker: Broker implementation for order execution
            portfolio_manager: Portfolio manager for position tracking
            position_tracker: Optional position tracker for trailing stops
            risk_controller: Optional Phase 4 RiskController for pre-execution gate
            stop_loss_manager: Optional Phase 4 StopLossManager for exit monitoring
            journal: Optional Phase 5 TradeJournal for persistent logging
            notifier: Optional Phase 6 Notifier for Telegram alerts
            min_confidence: Minimum confidence score to execute (0.0-1.0)
            max_daily_loss_pct: Max daily loss as % of equity to trigger kill switch
            cooldown_seconds: Minimum seconds between trades on same ticker
            require_confirmation: Require manual confirmation before live trades
            atr_timeframe: OHLCV timeframe for ATR calculation via CCXT (e.g. '1h', '4h', '1d')
        """
        self.broker = broker
        self.portfolio = portfolio_manager
        self.position_tracker = position_tracker
        self.risk_controller = risk_controller
        self.stop_loss_manager = stop_loss_manager
        self.journal = journal
        self.notifier = notifier
        self.min_confidence = min_confidence
        self.max_daily_loss_pct = max_daily_loss_pct
        self.cooldown_seconds = cooldown_seconds
        self.require_confirmation = require_confirmation
        self.atr_timeframe = atr_timeframe

        # Tracking
        self._last_trade_time: Dict[str, datetime] = {}  # ticker -> last trade time
        self._execution_log: List[Dict[str, Any]] = []
        self._kill_switch_active = False

        # Idempotency: track processed keys to prevent double orders
        self._processed_idempotency_keys: Set[str] = set()

        # ATR cache: {f"atr_{ticker}": (value, timestamp)} — 1-hour TTL
        self._atr_cache: Dict[str, tuple] = {}

        # Pending orders awaiting manual approval
        self._pending_orders: Dict[str, Dict[str, Any]] = {}

    # ── Idempotency ───────────────────────────────────────────────────

    @staticmethod
    def _generate_idempotency_key(decision: TradeDecision) -> str:
        """Generate a unique idempotency key for a trade decision.

        Format: {ticker}_{action}_{timestamp_ms}
        This prevents duplicate orders on network timeout/retry.
        """
        ts_ms = int(time.time() * 1000)
        return f"{decision.ticker}_{decision.action.value}_{ts_ms}"

    def _check_idempotency(self, key: str) -> bool:
        """Check if an idempotency key has already been processed.

        Returns True if the key is new (safe to proceed), False if duplicate.
        """
        if key in self._processed_idempotency_keys:
            return False
        self._processed_idempotency_keys.add(key)
        return True

    # ── Main Execution Flow ───────────────────────────────────────────

    def execute_decision(
        self,
        decision_json: str,
        current_price: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[OrderResult]:
        """Execute a structured trade decision.

        This is the main entry point. Parses the decision from JSON,
        runs pre-flight checks, executes via broker, and updates portfolio.

        Args:
            decision_json: JSON string from signal processor (TradeDecision format)
            current_price: Current market price (fetched from broker if None)
            idempotency_key: Optional client-provided idempotency key. If None,
                             one is auto-generated from {ticker}_{action}_{timestamp_ms}.

        Returns:
            OrderResult if trade was executed, None if skipped/rejected
        """
        # Step 1: Parse decision
        decision = self._parse_decision(decision_json)
        if decision is None:
            self._log("SKIP", "Could not parse trade decision from output")
            return None

        ticker = decision.ticker

        # Step 2: Generate or use provided idempotency key
        idem_key = idempotency_key or self._generate_idempotency_key(decision)
        if not self._check_idempotency(idem_key):
            self._log(
                "REJECTED",
                f"Duplicate order detected (idempotency key: {idem_key})",
                ticker=ticker,
            )
            return None

        # Step 3: Pre-flight checks
        rejection = self._pre_flight_checks(decision)
        if rejection:
            self._log("REJECTED", rejection, ticker=ticker)
            return None

        # Step 3.5: RiskController gate (Phase 4)
        if self.risk_controller:
            portfolio_state = self.portfolio.get_portfolio_state()

            # Auto-calculate ATR for volatility-adjusted sizing
            current_atr = self._get_atr(ticker)

            verdict = self.risk_controller.evaluate(
                decision, portfolio_state, current_atr=current_atr
            )

            if not verdict.approved:
                self._log(
                    "RISK_REJECTED",
                    f"RiskController rejected: {verdict.rejection_reason} "
                    f"(risk_score: {verdict.risk_score:.2f})",
                    ticker=ticker,
                )
                # Phase 5: Log rejection to trade journal
                if self.journal:
                    self.journal.log_rejection(decision, verdict)
                # Phase 6: Telegram alert on rejection
                if self.notifier:
                    self.notifier.send_rejection_alert(decision, verdict)
                return None

            # Use adjusted decision if provided (e.g., reduced sizing)
            if verdict.adjusted_decision:
                decision = verdict.adjusted_decision

            # Log warnings
            for warning in verdict.warnings:
                self._log("RISK_WARNING", warning, ticker=ticker)

            # Phase 5: Log approved decision to trade journal
            if self.journal:
                self.journal.log_decision(decision, verdict)

        # Step 4: Get current price
        if current_price is None:
            current_price = self.broker.get_current_price(ticker)
            if current_price is None:
                self._log("REJECTED", f"Cannot determine price for {ticker}", ticker=ticker)
                return None

        # Step 5: Calculate position size
        quantity = self.portfolio.calculate_position_size(decision, current_price)
        if quantity <= 0:
            self._log("SKIP", f"Position size is zero for {ticker}", ticker=ticker)
            return None

        # Step 6: Determine order side
        order_side = decision.to_order_side()
        if order_side is None:
            self._log("SKIP", f"HOLD — no order needed for {ticker}", ticker=ticker)
            return None

        # Step 7: Manual confirmation for live trades
        if self.require_confirmation:
            # Save to pending queue — do NOT execute yet
            pending_info = {
                "ticker": ticker,
                "action": decision.action.value,
                "quantity": quantity,
                "price": current_price,
                "value": round(quantity * current_price, 2),
                "confidence": decision.confidence_score,
                "stop_loss_pct": decision.stop_loss_pct,
                "take_profit_pct": decision.take_profit_pct,
                "order_type": getattr(decision, "order_type", "MARKET"),
                "time_horizon": getattr(decision, "time_horizon", None),
                "risk_reward_ratio": getattr(decision, "risk_reward_ratio", None),
                "reasoning": getattr(decision, "reasoning", ""),
                "key_factors": getattr(decision, "key_factors", []),
                "decision_json": decision_json,
                "idempotency_key": idem_key,
                "order_side": order_side,
            }

            # Store in in-memory queue for API layer to pick up
            self._pending_orders[idem_key] = pending_info

            self._log(
                "PENDING_APPROVAL",
                f"{decision.action.value} {quantity} {ticker} "
                f"@ ${current_price:,.4f} — awaiting manual approval",
                ticker=ticker,
            )

            logger.info(
                "Order saved to pending queue (key=%s). "
                "Approve via API or dashboard to execute.",
                idem_key,
            )
            return None  # Do NOT execute — await approval

        # Step 8: Execute order (only reached if require_confirmation=False)
        result = self.broker.place_order(
            ticker=ticker,
            side=order_side,
            quantity=quantity,
            order_type=decision.order_type,
            limit_price=decision.limit_price,
        )

        # Attach idempotency key to result
        if result:
            result = result.model_copy(update={"idempotency_key": idem_key})

        # Step 9: Post-execution handling
        if result.is_filled or result.is_partial:
            self._handle_fill(decision, result, current_price)
        elif result.is_failed:
            self._log("FAILED", f"Order failed: {result.error_message}", ticker=ticker)
        else:
            self._log("PENDING", f"Order submitted: {result.order_id}", ticker=ticker)

        return result

    # ── Decision Parsing ──────────────────────────────────────────────

    def _parse_decision(self, decision_json: str) -> Optional[TradeDecision]:
        """Parse a TradeDecision from JSON string or tagged text.

        Handles both pure JSON and text with embedded <TRADE_DECISION> tags.
        """
        if not decision_json or not decision_json.strip():
            return None

        text = decision_json.strip()

        # Try 1: Direct JSON parse
        try:
            data = json.loads(text)
            return TradeDecision(**data)
        except (json.JSONDecodeError, ValueError):
            pass

        # Try 2: Extract from <TRADE_DECISION> tags
        match = re.search(
            r"<TRADE_DECISION>\s*(.*?)\s*</TRADE_DECISION>",
            text,
            re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                return TradeDecision(**data)
            except (json.JSONDecodeError, ValueError):
                pass

        # Try 3: Extract from <RISK_ASSESSMENT> tags and build a minimal decision
        match = re.search(
            r"<RISK_ASSESSMENT>\s*(.*?)\s*</RISK_ASSESSMENT>",
            text,
            re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                # Build TradeDecision from RiskAssessment fields
                return TradeDecision(
                    action=data.get("adjusted_action", data.get("original_action", "HOLD")),
                    ticker=data.get("ticker", ""),
                    confidence_score=1.0 - data.get("risk_score", 0.5),
                    quantity_pct=data.get("adjusted_quantity_pct", 0.0),
                    stop_loss_pct=data.get("adjusted_stop_loss_pct"),
                    take_profit_pct=data.get("adjusted_take_profit_pct"),
                    reasoning=data.get("reasoning", ""),
                )
            except (json.JSONDecodeError, ValueError):
                pass

        # Try 4: Find any JSON object in the text
        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "action" in data:
                    return TradeDecision(**data)
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    # ── ATR Calculation ───────────────────────────────────────────────

    def _get_atr_ccxt(self, ticker: str, period: int = 14) -> Optional[float]:
        """Calculate ATR for a crypto ticker using CCXT OHLCV data.

        Fetches candlestick data from the exchange via the broker's CCXT
        instance and computes the Simple Moving Average of True Range.

        Args:
            ticker: CCXT-format symbol (e.g. 'BTC/USDT')
            period: ATR lookback period (default 14)

        Returns:
            ATR value as float, or None if unavailable.
        """
        # Guard: broker must be a CCXT broker with an exchange attribute
        exchange = getattr(self.broker, "exchange", None)
        if exchange is None:
            return None

        cache_key = f"atr_{ticker}"
        now = time.time()
        if cache_key in self._atr_cache:
            cached_val, cached_time = self._atr_cache[cache_key]
            if now - cached_time < 3600:  # 1-hour TTL
                return cached_val

        try:
            import ccxt as ccxt_lib

            ohlcv = exchange.fetch_ohlcv(
                ticker, timeframe=self.atr_timeframe, limit=period + 1
            )

            if ohlcv is None or len(ohlcv) < period + 1:
                logging.warning(
                    "[ExecutionEngine] Insufficient OHLCV data for %s "
                    "(got %d bars, need %d)",
                    ticker, len(ohlcv) if ohlcv else 0, period + 1,
                )
                self._atr_cache[cache_key] = (None, now)
                return None

            # OHLCV format: [timestamp, open, high, low, close, volume]
            true_ranges: list[float] = []
            for i in range(1, len(ohlcv)):
                high = ohlcv[i][2]
                low = ohlcv[i][3]
                prev_close = ohlcv[i - 1][4]

                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close),
                )
                true_ranges.append(tr)

            # SMA of the last `period` true ranges
            atr_value = sum(true_ranges[-period:]) / period

            self._atr_cache[cache_key] = (atr_value, now)
            return atr_value

        except ccxt_lib.NetworkError as e:
            logging.warning(
                "[ExecutionEngine] CCXT NetworkError fetching ATR for %s: %s",
                ticker, e,
            )
            self._atr_cache[cache_key] = (None, now)
            return None

        except ccxt_lib.ExchangeError as e:
            logging.warning(
                "[ExecutionEngine] CCXT ExchangeError fetching ATR for %s: %s",
                ticker, e,
            )
            self._atr_cache[cache_key] = (None, now)
            return None

        except Exception as e:
            logging.warning(
                "[ExecutionEngine] Unexpected error fetching ATR for %s: %s",
                ticker, e,
            )
            self._atr_cache[cache_key] = (None, now)
            return None

    def _get_atr(self, ticker: str, period: int = 14) -> Optional[float]:
        """Calculate Average True Range for a ticker.

        Uses CCXT OHLCV for crypto pairs (containing '/') and yfinance
        for traditional stock tickers. Results are cached for 1 hour.

        Args:
            ticker: Stock/crypto ticker
            period: ATR lookback period (default 14)

        Returns:
            ATR value as float, or None if calculation fails.
        """
        # Crypto pairs (CCXT format) — delegate to CCXT-based ATR
        if "/" in ticker:
            return self._get_atr_ccxt(ticker, period)

        # Check cache (1-hour TTL)
        cache_key = f"atr_{ticker}"
        now = time.time()
        if cache_key in self._atr_cache:
            cached_val, cached_time = self._atr_cache[cache_key]
            if now - cached_time < 3600:  # 1 hour
                return cached_val

        try:
            import yfinance as yf

            data = yf.Ticker(ticker).history(period="1mo", interval="1d")
            if data is None or len(data) < period + 1:
                self._atr_cache[cache_key] = (None, now)
                return None

            # Calculate True Range
            high = data["High"]
            low = data["Low"]
            close = data["Close"].shift(1)

            tr1 = high - low
            tr2 = (high - close).abs()
            tr3 = (low - close).abs()

            true_range = tr1.combine(tr2, max).combine(tr3, max)

            # ATR = SMA of True Range
            atr_value = float(true_range.iloc[-period:].mean())

            self._atr_cache[cache_key] = (atr_value, now)
            return atr_value

        except Exception:
            self._atr_cache[cache_key] = (None, now)
            return None

    # ── Pre-flight Checks ─────────────────────────────────────────────

    def _pre_flight_checks(self, decision: TradeDecision) -> Optional[str]:
        """Run safety checks before executing a trade.

        Returns rejection reason string, or None if all checks pass.
        """
        # Check 1: Kill switch
        if self._kill_switch_active:
            return "KILL SWITCH ACTIVE — all trading halted"

        # Check 2: Confidence threshold
        if decision.confidence_score < self.min_confidence:
            return (
                f"Confidence {decision.confidence_score:.2f} below "
                f"minimum {self.min_confidence:.2f}"
            )

        # Check 3: HOLD action
        if decision.action == TradeAction.HOLD:
            return "Action is HOLD — no trade needed"

        # Check 4: Cooldown period
        if decision.ticker in self._last_trade_time:
            elapsed = (datetime.utcnow() - self._last_trade_time[decision.ticker]).total_seconds()
            if elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - elapsed
                return f"Cooldown active — {remaining:.0f}s remaining for {decision.ticker}"

        # Check 5: Daily loss limit
        if self.portfolio.max_drawdown_pct >= self.max_daily_loss_pct:
            self._kill_switch_active = True
            reason = (
                f"Daily loss limit exceeded: {self.portfolio.max_drawdown_pct:.1%} >= "
                f"{self.max_daily_loss_pct:.1%}. KILL SWITCH ACTIVATED."
            )
            # Phase 6: Telegram alert on kill switch
            if self.notifier:
                self.notifier.send_kill_switch_alert(
                    reason=reason,
                    total_loss=self.portfolio.total_pnl,
                )
            return reason

        # Check 6: Already has position in same ticker (for BUY)
        if decision.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            existing = self.portfolio.positions.get(decision.ticker)
            if existing and existing.side == OrderSide.BUY:
                return (
                    f"Already have BUY position in {decision.ticker}. "
                    f"Close existing position first or increase it manually."
                )

        return None  # All checks passed

    # ── Post-execution ────────────────────────────────────────────────

    def _handle_fill(
        self, decision: TradeDecision, result: OrderResult, current_price: float
    ):
        """Handle a filled order — update portfolio and tracking."""
        fill_price = result.effective_fill_price or current_price
        ticker = decision.ticker

        # Calculate stop-loss and take-profit prices
        sl_price = decision.calculate_stop_loss_price(fill_price)
        tp_price = decision.calculate_take_profit_price(fill_price)

        if result.side == OrderSide.BUY:
            # Open new position in portfolio manager
            self.portfolio.open_position(
                ticker=ticker,
                side=OrderSide.BUY,
                quantity=result.filled_quantity,
                entry_price=fill_price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
            )

            # Register with position tracker
            if self.position_tracker:
                pos = self.portfolio.positions.get(ticker)
                if pos:
                    self.position_tracker.register_position(pos)

            # Critical Fix #3: Auto-register with StopLossManager
            if self.stop_loss_manager:
                pos = self.portfolio.positions.get(ticker)
                if pos:
                    self.stop_loss_manager.register_position(pos)

            # Phase 5: Log BUY fill to trade journal
            if self.journal:
                self.journal.log_fill(result)

            # Phase 6: Telegram alert on BUY fill
            if self.notifier:
                self.notifier.send_trade_alert(result, ticker)

        elif result.side == OrderSide.SELL:
            # Close existing position
            pnl = self.portfolio.close_position(
                ticker=ticker,
                exit_price=fill_price,
                reasoning=decision.reasoning,
            )

            # Unregister from tracker
            if self.position_tracker:
                self.position_tracker.unregister_position(ticker)

            # Unregister from StopLossManager
            if self.stop_loss_manager:
                self.stop_loss_manager.unregister_position(ticker)

            # Critical Fix #2: Record trade result for consecutive loss tracking
            if pnl is not None and self.risk_controller:
                self.risk_controller.record_trade_result(pnl, ticker)

            if pnl is not None:
                pnl_str = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
                self._log("CLOSED", f"{ticker} — P&L: {pnl_str}", ticker=ticker)

                # Phase 5: Log fill with realized PnL
                if self.journal:
                    self.journal.log_fill(result, realized_pnl=pnl)
            elif self.journal:
                self.journal.log_fill(result)

            # Phase 6: Telegram alert on SELL fill
            if self.notifier:
                self.notifier.send_trade_alert(result, ticker)

        # Update cooldown
        self._last_trade_time[ticker] = datetime.utcnow()

        # Log for partial vs full fill
        fill_type = "PARTIAL_FILL" if result.is_partial else "FILLED"

        # Log execution
        self._log(
            fill_type,
            f"{result.side.value} {result.filled_quantity} {ticker} "
            f"@ ${fill_price:,.4f} via {self.broker.name}"
            f"{f' (remaining: {result.remaining_quantity})' if result.remaining_quantity > 0 else ''}",
            ticker=ticker,
            extra={
                "order_id": result.order_id,
                "idempotency_key": result.idempotency_key,
                "commission": result.commission,
                "stop_loss": sl_price,
                "take_profit": tp_price,
                "confidence": decision.confidence_score,
                "remaining_quantity": result.remaining_quantity,
            },
        )

    # ── Critical Fix #1: StopLoss → Broker Exit Pipeline ─────────────

    def process_exit_signals(
        self,
        current_prices: Optional[Dict[str, float]] = None,
        atr_values: Optional[Dict[str, float]] = None,
    ) -> List[OrderResult]:
        """Check stop-loss conditions and auto-execute exits.

        This should be called periodically (e.g., on every price tick or
        on a timer) to monitor positions and execute stop-loss exits.

        Args:
            current_prices: Dict of ticker -> current price.
                           If None, fetches from broker for each tracked position.
            atr_values: Optional dict of ticker -> current ATR value.

        Returns:
            List of OrderResults for executed exit orders.
        """
        if not self.stop_loss_manager:
            return []

        # Fetch prices if not provided
        if current_prices is None:
            current_prices = {}
            for ticker in list(self.stop_loss_manager._positions.keys()):
                price = self.broker.get_current_price(ticker)
                if price is not None:
                    current_prices[ticker] = price

        if not current_prices:
            return []

        # Check for exit signals
        signals = self.stop_loss_manager.check_exits(current_prices, atr_values)

        if not signals:
            return []

        # Execute each exit signal
        results: List[OrderResult] = []
        for signal in signals:
            self._log(
                "EXIT_SIGNAL",
                f"{signal.reason.value}: {signal.ticker} — {signal.detail}",
                ticker=signal.ticker,
                extra={
                    "trigger_price": signal.trigger_price,
                    "current_price": signal.current_price,
                    "high_watermark": signal.high_watermark,
                    "entry_price": signal.entry_price,
                    "pnl_pct": f"{signal.pnl_pct:.2%}",
                    "urgency": signal.urgency,
                },
            )

            # Get current position to determine sell quantity
            pos = self.portfolio.positions.get(signal.ticker)
            if pos is None:
                self._log("SKIP", f"No position found for {signal.ticker} (already closed?)",
                          ticker=signal.ticker)
                continue

            # Execute SELL order
            try:
                result = self.broker.place_order(
                    ticker=signal.ticker,
                    side=OrderSide.SELL,
                    quantity=pos.quantity,
                    order_type=OrderType.MARKET,
                )

                if result and (result.is_filled or result.is_partial):
                    fill_price = result.effective_fill_price or signal.current_price

                    # Close position in portfolio
                    pnl = self.portfolio.close_position(
                        ticker=signal.ticker,
                        exit_price=fill_price,
                        reasoning=f"Auto-exit: {signal.reason.value} — {signal.detail}",
                    )

                    # Unregister from trackers
                    if self.position_tracker:
                        self.position_tracker.unregister_position(signal.ticker)
                    self.stop_loss_manager.unregister_position(signal.ticker)

                    # Record trade result for consecutive loss tracking
                    if pnl is not None and self.risk_controller:
                        self.risk_controller.record_trade_result(pnl, signal.ticker)

                    pnl_str = f"+${pnl:,.2f}" if (pnl or 0) >= 0 else f"-${abs(pnl or 0):,.2f}"
                    self._log(
                        "CLOSED",
                        f"{signal.ticker} auto-exit ({signal.reason.value}) — P&L: {pnl_str}",
                        ticker=signal.ticker,
                    )

                results.append(result)

            except Exception as e:
                self._log(
                    "FAILED",
                    f"Exit order failed for {signal.ticker}: {e}",
                    ticker=signal.ticker,
                )

        return results

    # ── Kill Switch ───────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "Manual activation"):
        """Activate kill switch — halt all trading and optionally close positions."""
        self._kill_switch_active = True
        self._log("KILL_SWITCH", f"Activated: {reason}")
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

    def deactivate_kill_switch(self):
        """Deactivate kill switch — resume trading."""
        self._kill_switch_active = False
        self._log("KILL_SWITCH", "Deactivated — trading resumed")
        logger.info("Kill switch deactivated — trading resumed")

    def emergency_close_all(self) -> List[OrderResult]:
        """Emergency: close all positions immediately."""
        self.activate_kill_switch("Emergency close all")
        results = self.broker.close_all_positions()
        for r in results:
            if r.is_filled:
                self.portfolio.close_position(r.ticker, r.filled_price or 0, "Emergency close")
        return results

    # ── Logging ───────────────────────────────────────────────────────

    def _log(
        self,
        action: str,
        message: str,
        ticker: str = "",
        extra: Optional[dict] = None,
    ):
        """Log an execution event."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "ticker": ticker,
            "message": message,
            "extra": extra or {},
        }
        self._execution_log.append(entry)

        # Print to console
        symbol = {
            "FILLED": "✅",
            "PARTIAL_FILL": "⚠️",
            "REJECTED": "❌",
            "FAILED": "❌",
            "SKIP": "⏭️",
            "CLOSED": "📤",
            "PENDING": "⏳",
            "KILL_SWITCH": "🚨",
            "RISK_REJECTED": "🛡️",
            "RISK_WARNING": "⚠️",
            "EXIT_SIGNAL": "🔻",
        }.get(action, "📋")

        logger.info("%s %s: %s", symbol, action, message)

    def get_execution_log(self) -> List[Dict[str, Any]]:
        """Get the full execution log."""
        return self._execution_log.copy()

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        return {
            "broker": self.broker.name,
            "kill_switch": self._kill_switch_active,
            "min_confidence": self.min_confidence,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "cooldown_seconds": self.cooldown_seconds,
            "require_confirmation": self.require_confirmation,
            "open_positions": len(self.portfolio.positions),
            "total_trades": self.portfolio.total_trades,
            "current_equity": self.portfolio.total_equity,
            "daily_pnl": self.portfolio.daily_pnl,
            "idempotency_keys_tracked": len(self._processed_idempotency_keys),
            "executions_today": len([
                e for e in self._execution_log
                if e["action"] in ("FILLED", "PARTIAL_FILL")
                and e["timestamp"][:10] == datetime.utcnow().isoformat()[:10]
            ]),
        }

    # ── Reconciliation ────────────────────────────────────────────────

    def reconcile(self) -> Dict[str, Any]:
        """Reconcile local portfolio with actual broker positions.

        Should be called on startup to detect and fix drift caused by
        downtime, missed fills, or external trades.

        Behaviour:
        1. Fetch live positions from broker
        2. Positions on exchange but NOT in local portfolio → add locally
        3. Positions in local portfolio but NOT on exchange → remove locally
        4. Matching positions → update current_price

        Returns:
            Dict with keys: added, removed, updated, errors, summary
        """
        report: Dict[str, Any] = {
            "added": [],
            "removed": [],
            "updated": [],
            "errors": [],
        }

        try:
            exchange_positions = self.broker.get_positions()
        except Exception as e:
            logger.error("Reconciliation failed: cannot fetch broker positions: %s", e)
            report["errors"].append(f"broker.get_positions() failed: {e}")
            report["summary"] = "Reconciliation aborted — broker unreachable"
            self._log("RECONCILE", f"FAILED: {e}")
            return report

        # Build lookup: ticker → PositionInfo
        exchange_map: Dict[str, PositionInfo] = {
            pos.ticker: pos for pos in exchange_positions
        }
        local_tickers = set(self.portfolio.positions.keys())
        exchange_tickers = set(exchange_map.keys())

        # 1. Positions on exchange but NOT in local portfolio → add
        for ticker in exchange_tickers - local_tickers:
            pos = exchange_map[ticker]
            self.portfolio.open_position(
                ticker=ticker,
                side=pos.side,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
            )
            report["added"].append(ticker)
            logger.info(
                "Reconciled: added %s %s %s @ %.4f (found on exchange, missing locally)",
                pos.side.value, pos.quantity, ticker, pos.entry_price,
            )

        # 2. Positions in local portfolio but NOT on exchange → remove
        for ticker in local_tickers - exchange_tickers:
            local_pos = self.portfolio.positions[ticker]
            self.portfolio.close_position(
                ticker=ticker,
                exit_price=local_pos.current_price,
                reasoning="Reconciliation: position no longer on exchange",
            )
            report["removed"].append(ticker)
            logger.warning(
                "Reconciled: removed %s (in local portfolio but not on exchange)",
                ticker,
            )

        # 3. Matching positions → update current_price
        for ticker in exchange_tickers & local_tickers:
            pos = exchange_map[ticker]
            self.portfolio.update_prices({ticker: pos.current_price})
            report["updated"].append(ticker)

        # Update cash balance from broker
        try:
            balance = self.broker.get_balance()
            broker_cash = balance.get("cash", 0.0)
            if broker_cash > 0:
                old_cash = self.portfolio.cash_balance
                self.portfolio.cash_balance = broker_cash
                if abs(old_cash - broker_cash) > 0.01:
                    logger.info(
                        "Reconciled cash: $%.2f → $%.2f",
                        old_cash, broker_cash,
                    )
        except Exception as e:
            report["errors"].append(f"get_balance() failed: {e}")

        report["summary"] = (
            f"Reconciliation complete: "
            f"+{len(report['added'])} added, "
            f"-{len(report['removed'])} removed, "
            f"~{len(report['updated'])} updated"
        )

        self._log("RECONCILE", report["summary"])
        logger.info(report["summary"])

        return report

    # ── Pending Order Management ──────────────────────────────────────

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get all pending orders awaiting manual approval."""
        return list(self._pending_orders.values())

    def approve_pending_order(self, idempotency_key: str) -> Optional[OrderResult]:
        """Approve and execute a pending order.

        Removes the order from the pending queue and sends it
        to the broker.

        Args:
            idempotency_key: The unique key of the pending order

        Returns:
            OrderResult if trade was executed, None if not found or failed
        """
        pending = self._pending_orders.pop(idempotency_key, None)
        if pending is None:
            logger.warning("No pending order found with key=%s", idempotency_key)
            return None

        ticker = pending["ticker"]
        quantity = pending["quantity"]
        order_side = pending["order_side"]
        current_price = pending["price"]

        self._log(
            "APPROVED",
            f"{pending['action']} {quantity} {ticker} "
            f"@ ${current_price:,.4f} — approved by user",
            ticker=ticker,
        )

        # Parse order_type from pending info
        order_type_str = pending.get("order_type", "MARKET")
        order_type = OrderType.MARKET
        if order_type_str == "LIMIT":
            order_type = OrderType.LIMIT

        # Execute the order
        try:
            result = self.broker.place_order(
                ticker=ticker,
                side=order_side,
                quantity=quantity,
                order_type=order_type,
            )

            if result and (result.is_filled or result.is_partial):
                # Re-parse decision for portfolio update
                decision = self._parse_decision(pending["decision_json"])
                if decision:
                    self._handle_fill(decision, result, current_price)

            return result

        except Exception as e:
            self._log("FAILED", f"Approved order execution failed: {e}", ticker=ticker)
            logger.error("Failed to execute approved order %s: %s", idempotency_key, e)
            return None

    def reject_pending_order(self, idempotency_key: str) -> bool:
        """Reject a pending order — removes it from queue without executing.

        Args:
            idempotency_key: The unique key of the pending order

        Returns:
            True if order was found and rejected, False if not found
        """
        pending = self._pending_orders.pop(idempotency_key, None)
        if pending is None:
            logger.warning("No pending order found with key=%s", idempotency_key)
            return False

        self._log(
            "REJECTED_BY_USER",
            f"{pending['action']} {pending['quantity']} {pending['ticker']} "
            f"— rejected by user",
            ticker=pending["ticker"],
        )
        return True
