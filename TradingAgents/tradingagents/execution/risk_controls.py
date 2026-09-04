"""Risk controls for pre-execution trade validation.

Implements a synchronous risk gate that the ExecutionEngine calls
before submitting any order to a broker. All checks are blocking
and deterministic — no async monitoring (that comes in Phase 6).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from collections import defaultdict
from enum import Enum
from typing import Any, Optional, Dict, List, Set

logger = logging.getLogger(__name__)

from tradingagents.execution.order_models import (
    TradeAction,
    TradeDecision,
    OrderSide,
    PositionInfo,
    PortfolioState,
)


# ── Sector/Asset-class mapping for correlation check ─────────────────

# Maps tickers to sector codes. Expand as needed.
_SECTOR_MAP: Dict[str, str] = {
    # US Tech
    "AAPL": "tech", "MSFT": "tech", "GOOGL": "tech", "GOOG": "tech",
    "META": "tech", "NVDA": "tech", "AMD": "tech", "INTC": "tech",
    "AMZN": "tech", "NFLX": "tech", "TSLA": "tech_auto", "CRM": "tech",
    "AVGO": "tech", "ORCL": "tech", "ADBE": "tech", "CSCO": "tech",
    # Finance
    "JPM": "finance", "BAC": "finance", "GS": "finance", "MS": "finance",
    "V": "finance", "MA": "finance", "WFC": "finance", "C": "finance",
    "BRK-B": "finance", "AXP": "finance", "SCHW": "finance",
    # Healthcare
    "JNJ": "health", "UNH": "health", "PFE": "health", "MRK": "health",
    "ABBV": "health", "LLY": "health", "TMO": "health", "ABT": "health",
    # Energy
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "EOG": "energy", "MPC": "energy", "PSX": "energy",
    # Consumer
    "KO": "consumer", "PEP": "consumer", "PG": "consumer", "WMT": "consumer",
    "COST": "consumer", "MCD": "consumer", "NKE": "consumer", "SBUX": "consumer",
    # Industrial
    "BA": "industrial", "CAT": "industrial", "HON": "industrial", "UPS": "industrial",
    "GE": "industrial", "RTX": "industrial", "MMM": "industrial", "DE": "industrial",
    # Real Estate
    "AMT": "realestate", "PLD": "realestate", "CCI": "realestate",
    # Telecom
    "T": "telecom", "VZ": "telecom", "TMUS": "telecom",
    # Crypto (CCXT-style)
    "BTC": "crypto_major", "BTC/USDT": "crypto_major",
    "ETH": "crypto_major", "ETH/USDT": "crypto_major",
    "SOL": "crypto_alt", "SOL/USDT": "crypto_alt",
    "DOGE": "crypto_meme", "DOGE/USDT": "crypto_meme",
    "SHIB": "crypto_meme", "SHIB/USDT": "crypto_meme",
    "ADA": "crypto_alt", "ADA/USDT": "crypto_alt",
    "XRP": "crypto_alt", "XRP/USDT": "crypto_alt",
    "BNB": "crypto_exchange", "BNB/USDT": "crypto_exchange",
    "AVAX": "crypto_alt", "AVAX/USDT": "crypto_alt",
    "DOT": "crypto_alt", "DOT/USDT": "crypto_alt",
    "LINK": "crypto_defi", "LINK/USDT": "crypto_defi",
    "UNI": "crypto_defi", "UNI/USDT": "crypto_defi",
}

# Cache for dynamic sector lookups via yfinance
_SECTOR_CACHE: Dict[str, Optional[str]] = {}


def _resolve_sector(ticker: str) -> str:
    """Resolve sector for a ticker.

    Priority:
    1. Hardcoded _SECTOR_MAP (instant)
    2. Cached yfinance lookup
    3. Live yfinance fallback (slow, cached after first call)
    4. "unknown" if all else fails
    """
    # Check static map
    if ticker in _SECTOR_MAP:
        return _SECTOR_MAP[ticker]

    # Check cache
    if ticker in _SECTOR_CACHE:
        return _SECTOR_CACHE[ticker] or "unknown"

    # Try yfinance lookup (only for stock-like tickers, not crypto pairs)
    if "/" not in ticker:
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info
            sector = info.get("sector", "")
            if sector:
                # Normalize to lowercase short name
                sector_key = sector.lower().replace(" ", "_")
                _SECTOR_CACHE[ticker] = sector_key
                _SECTOR_MAP[ticker] = sector_key  # Cache permanently
                return sector_key
        except Exception:
            pass

    _SECTOR_CACHE[ticker] = None
    return "unknown"


@dataclass
class RiskVerdict:
    """Result of a RiskController evaluation.

    Attributes:
        approved: Whether the trade is approved to proceed
        adjusted_decision: Possibly adjusted TradeDecision (e.g., reduced sizing)
        rejection_reason: Human-readable rejection reason (if not approved)
        risk_score: Aggregate risk score 0.0 (safe) to 1.0 (maximum risk)
        warnings: Non-blocking warnings (trade still allowed but flagged)
    """
    approved: bool = True
    adjusted_decision: Optional[TradeDecision] = None
    rejection_reason: str = ""
    risk_score: float = 0.0
    warnings: List[str] = field(default_factory=list)


class DrawdownPeriod(str, Enum):
    """Drawdown measurement window."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class RiskController:
    """Synchronous pre-execution risk gate.

    Called by ExecutionEngine before submitting to broker.
    Checks hard limits, correlation, sizing, and kill switch.

    Usage:
        rc = RiskController(max_drawdown_pct={"daily": 0.05})
        verdict = rc.evaluate(decision, portfolio_state)
        if not verdict.approved:
            print(verdict.rejection_reason)
    """

    def __init__(
        self,
        max_drawdown_pct: Optional[Dict[str, float]] = None,
        max_position_pct: float = 0.10,
        max_concurrent_positions: int = 10,
        max_sector_concentration: float = 0.30,
        max_correlation_sectors: int = 2,
        risk_per_trade_pct: float = 0.02,
        consecutive_loss_limit: int = 3,
        consecutive_loss_cooldown_seconds: int = 3600,
        max_leverage: int = 10,
        db: Optional[Any] = None,
        account_id: str = "default",
    ):
        """Initialize risk controller.

        Args:
            max_drawdown_pct: Max drawdown per period {"daily": 0.05, "weekly": 0.10, "monthly": 0.15}
            max_position_pct: Max % of equity per single position (default 10%)
            max_concurrent_positions: Max number of open positions allowed
            max_sector_concentration: Max % of equity in one sector (default 30%)
            max_correlation_sectors: Max positions in the same sector
            risk_per_trade_pct: Risk budget per trade for ATR sizing (default 2%)
            consecutive_loss_limit: N consecutive losses triggers cooldown
            max_leverage: Hard cap on leverage multiplier (default 10)
            db: tradingagents.storage.database.Database for durable risk
                state. Without it this controller is memory-only, which is
                UNSAFE in any deployment that constructs a new controller
                per analysis (the SaaS API does exactly that): the kill
                switch and the loss history it depends on would reset
                before every decision.
            account_id: Scopes the persisted state. The database file is
                shared across users, so this must be unique per trading
                account or one user's halt state would leak into another's.
        """
        self.max_drawdown_pct = max_drawdown_pct or {
            "daily": 0.05,
            "weekly": 0.10,
            "monthly": 0.15,
        }
        self.max_position_pct = max_position_pct
        self.max_concurrent_positions = max_concurrent_positions
        self.max_sector_concentration = max_sector_concentration
        self.max_correlation_sectors = max_correlation_sectors
        self.risk_per_trade_pct = risk_per_trade_pct
        self.consecutive_loss_limit = consecutive_loss_limit
        self.consecutive_loss_cooldown_seconds = consecutive_loss_cooldown_seconds
        self.max_leverage = max_leverage

        # Persistence
        self._db = db
        self._account_id = account_id

        # State
        self._kill_switch = False
        self._kill_switch_reason = ""
        self._kill_switch_activated_date: Optional[date] = None  # For auto-recovery
        self._consecutive_losses = 0
        self._last_loss_time: Optional[datetime] = None
        self._trade_results: List[Dict] = []  # {pnl, ticker, timestamp}
        self._pnl_tracker = _PnLTracker()  # Per-period drawdown tracking

        self._load_persisted_state()

    # ── Main evaluate() ───────────────────────────────────────────────

    def evaluate(
        self,
        decision: TradeDecision,
        portfolio: PortfolioState,
        current_atr: Optional[float] = None,
    ) -> RiskVerdict:
        """Evaluate a trade decision against all risk rules.

        Args:
            decision: The proposed trade decision
            portfolio: Current portfolio state
            current_atr: Current ATR value for the ticker (optional, for ATR sizing)

        Returns:
            RiskVerdict with approval status and possibly adjusted decision
        """
        warnings: List[str] = []
        risk_score = 0.0

        # ── Check 1: Kill switch (with auto-recovery) ─────────────────
        self._check_kill_switch_auto_recovery()
        if self._kill_switch:
            return RiskVerdict(
                approved=False,
                rejection_reason=f"KILL SWITCH: {self._kill_switch_reason}",
                risk_score=1.0,
            )

        # ── Check 2: Consecutive loss cooldown ────────────────────────
        cooldown_msg = self._check_consecutive_loss_cooldown()
        if cooldown_msg:
            return RiskVerdict(
                approved=False,
                rejection_reason=cooldown_msg,
                risk_score=0.8,
            )

        # ── Check 3: Drawdown limits ──────────────────────────────────
        drawdown_msg = self._check_drawdown_limits(portfolio)
        if drawdown_msg:
            self.activate_kill_switch(drawdown_msg)
            return RiskVerdict(
                approved=False,
                rejection_reason=drawdown_msg,
                risk_score=1.0,
            )

        # ── Check 4: Max concurrent positions ─────────────────────────
        if decision.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            if portfolio.position_count >= self.max_concurrent_positions:
                return RiskVerdict(
                    approved=False,
                    rejection_reason=(
                        f"Max positions reached: {portfolio.position_count} "
                        f">= {self.max_concurrent_positions}"
                    ),
                    risk_score=0.7,
                )

        # ── Check 5: Position size limit ──────────────────────────────
        adjusted_decision = decision
        if decision.quantity_pct and decision.quantity_pct > self.max_position_pct:
            old_pct = decision.quantity_pct
            adjusted_decision = TradeDecision(
                **{
                    **decision.model_dump(),
                    "quantity_pct": self.max_position_pct,
                }
            )
            warnings.append(
                f"Position size reduced: {old_pct:.1%} -> {self.max_position_pct:.1%}"
            )
            risk_score += 0.2

        # ── Check 6a: Leverage cap (futures) ──────────────────────────
        decision_leverage = getattr(adjusted_decision, 'leverage', 1)
        if decision_leverage > self.max_leverage:
            return RiskVerdict(
                approved=False,
                rejection_reason=(
                    f"Leverage {decision_leverage}x exceeds max allowed "
                    f"{self.max_leverage}x"
                ),
                risk_score=0.9,
            )

        # ── Check 6b: Liquidation proximity warning (futures) ─────────
        if decision_leverage > 1:
            liq_distance = 1.0 / decision_leverage
            if liq_distance < 0.05:
                warnings.append(
                    f"⚠️ High leverage {decision_leverage}x — liquidation at "
                    f"{liq_distance:.1%} from entry"
                )
                risk_score += 0.3
            elif liq_distance < 0.10:
                warnings.append(
                    f"Leverage {decision_leverage}x — liquidation at "
                    f"{liq_distance:.1%} from entry"
                )
                risk_score += 0.15

        # ── Check 6c: Leverage-adjusted position sizing ───────────────
        if decision_leverage > 1 and adjusted_decision.quantity_pct:
            effective_max = self.max_position_pct / decision_leverage
            if adjusted_decision.quantity_pct > effective_max:
                old_pct = adjusted_decision.quantity_pct
                adjusted_decision = TradeDecision(
                    **{
                        **adjusted_decision.model_dump(),
                        "quantity_pct": round(effective_max, 4),
                    }
                )
                warnings.append(
                    f"Leverage-adjusted size: {old_pct:.1%} → {effective_max:.1%} "
                    f"(max_pos {self.max_position_pct:.0%} / {decision_leverage}x)"
                )

        # ── Check 7: Correlation check ────────────────────────────────────
        if decision.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            corr_msg = self._check_correlation(decision.ticker, portfolio.open_positions)
            if corr_msg:
                return RiskVerdict(
                    approved=False,
                    rejection_reason=corr_msg,
                    risk_score=0.6,
                )

        # ── Check 7: Sector concentration ─────────────────────────────
        sector_warning = self._check_sector_concentration(
            decision.ticker, portfolio.open_positions, portfolio.total_equity
        )
        if sector_warning:
            warnings.append(sector_warning)
            risk_score += 0.15

        # ── Check 8: ATR-based sizing override ────────────────────────
        if current_atr and current_atr > 0 and decision.action in (TradeAction.BUY, TradeAction.STRONG_BUY):
            atr_decision = self._volatility_adjusted_sizing(
                adjusted_decision, current_atr, portfolio.total_equity
            )
            if atr_decision:
                old_pct = adjusted_decision.quantity_pct or 0
                adjusted_decision = atr_decision
                if atr_decision.quantity_pct and atr_decision.quantity_pct != old_pct:
                    warnings.append(
                        f"ATR-adjusted size: {old_pct:.1%} -> {atr_decision.quantity_pct:.1%}"
                    )

        # ── Aggregate risk score ──────────────────────────────────────
        # Add base confidence-inverse risk
        risk_score += (1.0 - decision.confidence_score) * 0.3
        risk_score = min(risk_score, 1.0)

        return RiskVerdict(
            approved=True,
            adjusted_decision=adjusted_decision,
            risk_score=risk_score,
            warnings=warnings,
        )

    # ── Individual Checks ─────────────────────────────────────────────

    def _check_drawdown_limits(self, portfolio: PortfolioState) -> Optional[str]:
        """Check if any drawdown limit has been breached.

        Uses per-period PnL tracking for accurate daily/weekly/monthly comparison.
        Falls back to portfolio.max_drawdown_pct if no trades recorded yet.
        """
        # Get per-period drawdowns from PnL tracker
        period_drawdowns = self._pnl_tracker.get_drawdowns(portfolio.total_equity)

        for period, limit in self.max_drawdown_pct.items():
            # Use tracked per-period drawdown if available, else fall back to portfolio-level
            if period in period_drawdowns:
                current_dd = period_drawdowns[period]
            else:
                current_dd = portfolio.max_drawdown_pct or 0.0

            if current_dd >= limit:
                return (
                    f"Drawdown limit breached ({period}): "
                    f"{current_dd:.1%} >= {limit:.1%}"
                )
        return None

    def _check_consecutive_loss_cooldown(self) -> Optional[str]:
        """Check if we're in a cooldown period after consecutive losses."""
        if self._consecutive_losses < self.consecutive_loss_limit:
            return None

        if self._last_loss_time:
            elapsed = (datetime.utcnow() - self._last_loss_time).total_seconds()
            if elapsed < self.consecutive_loss_cooldown_seconds:
                remaining = self.consecutive_loss_cooldown_seconds - elapsed
                return (
                    f"Consecutive loss cooldown: {self._consecutive_losses} losses in a row. "
                    f"{remaining:.0f}s remaining"
                )
            else:
                # Cooldown expired, reset counter
                self._consecutive_losses = 0

        return None

    def _check_correlation(
        self, ticker: str, open_positions: List[PositionInfo]
    ) -> Optional[str]:
        """Reject if new ticker correlates too strongly with existing positions.

        Uses sector/asset-class mapping to detect correlation.
        """
        new_sector = _resolve_sector(ticker)
        if new_sector == "unknown":
            return None  # Can't check unknown sector

        # Count positions in same sector
        same_sector_count = 0
        for pos in open_positions:
            pos_sector = _resolve_sector(pos.ticker)
            if pos_sector == new_sector:
                same_sector_count += 1

        if same_sector_count >= self.max_correlation_sectors:
            return (
                f"Correlation limit: already have {same_sector_count} positions "
                f"in sector '{new_sector}'. Max: {self.max_correlation_sectors}"
            )

        return None

    def _check_sector_concentration(
        self, ticker: str, open_positions: List[PositionInfo], total_equity: float
    ) -> Optional[str]:
        """Warn if sector concentration exceeds threshold."""
        new_sector = _resolve_sector(ticker)
        if new_sector == "unknown" or not open_positions:
            return None

        if total_equity <= 0:
            return None

        # Sum sector exposure from existing positions
        sector_value = 0.0
        for pos in open_positions:
            pos_sector = _resolve_sector(pos.ticker)
            if pos_sector == new_sector:
                sector_value += pos.quantity * pos.current_price

        sector_pct = sector_value / total_equity
        if sector_pct >= self.max_sector_concentration:
            return (
                f"High sector concentration: '{new_sector}' is "
                f"{sector_pct:.1%} of equity (limit: {self.max_sector_concentration:.1%})"
            )

        return None

    def _volatility_adjusted_sizing(
        self,
        decision: TradeDecision,
        atr: float,
        equity: float,
    ) -> Optional[TradeDecision]:
        """Override position size using ATR-based volatility adjustment.

        Formula: position_size_value = (equity * risk_per_trade_pct) / atr
                 quantity_pct = position_size_value / equity

        This ensures each trade risks the same dollar amount regardless
        of the underlying's volatility.

        Args:
            decision: Original trade decision
            atr: Current Average True Range for the ticker
            equity: Current portfolio equity

        Returns:
            Adjusted TradeDecision with new quantity_pct, or None if no change needed
        """
        if equity <= 0 or atr <= 0:
            return None

        # Dollar risk budget for this trade
        risk_budget = equity * self.risk_per_trade_pct

        # Position value that keeps risk within budget
        # (We assume 1 ATR of adverse move = our risk per trade)
        position_value = risk_budget / atr * 1.0  # multiply by estimated price later

        # Express as fraction of equity
        atr_pct = min(position_value / equity, self.max_position_pct)

        # Only adjust if ATR sizing is more conservative
        original_pct = decision.quantity_pct or 0.0
        if atr_pct < original_pct:
            return TradeDecision(
                **{
                    **decision.model_dump(),
                    "quantity_pct": round(atr_pct, 4),
                }
            )

        return None

    # ── Durable State ─────────────────────────────────────────────────

    def _load_persisted_state(self) -> None:
        """Restore kill switch, loss streak and PnL window from the database.

        A failure here must NOT be silent and must NOT be treated as "no
        halt in effect": if we cannot read the risk state, we cannot know
        whether trading was halted, and the safe assumption is that it was.
        """
        if self._db is None:
            return
        try:
            row = self._db.load_risk_state(self._account_id)
        except Exception as e:
            logger.error(
                "Could not read risk state for %s (%s) — engaging kill switch. "
                "Trading stays halted until the state store is readable.",
                self._account_id, e,
            )
            self._kill_switch = True
            self._kill_switch_reason = "Risk state unreadable (fail-closed)"
            self._kill_switch_activated_date = datetime.utcnow().date()
            return

        if not row:
            return

        self._kill_switch = bool(row.get("kill_switch"))
        self._kill_switch_reason = row.get("kill_switch_reason") or ""

        raw_date = row.get("kill_switch_activated_date")
        if raw_date:
            try:
                self._kill_switch_activated_date = date.fromisoformat(raw_date)
            except (TypeError, ValueError):
                # Unparseable date would disable auto-recovery forever;
                # treat the halt as starting today instead of dropping it.
                self._kill_switch_activated_date = datetime.utcnow().date()

        self._consecutive_losses = int(row.get("consecutive_losses") or 0)

        raw_loss_time = row.get("last_loss_time")
        if raw_loss_time:
            try:
                self._last_loss_time = datetime.fromisoformat(raw_loss_time)
            except (TypeError, ValueError):
                self._last_loss_time = None

        try:
            self._pnl_tracker.load_state(json.loads(row.get("pnl_window_json") or "[]"))
        except (TypeError, ValueError) as e:
            logger.warning("Could not restore PnL window for %s: %s", self._account_id, e)

        if self._kill_switch:
            logger.critical(
                "Restored ACTIVE kill switch for %s: %s",
                self._account_id, self._kill_switch_reason,
            )

    def _persist_state(self) -> None:
        """Write current risk state. Never raises — a persistence failure
        must not abort an in-flight risk decision, but it is logged loudly
        because the next process start would silently lose the halt."""
        if self._db is None:
            return
        try:
            self._db.save_risk_state(
                account_id=self._account_id,
                kill_switch=self._kill_switch,
                kill_switch_reason=self._kill_switch_reason,
                kill_switch_activated_date=(
                    self._kill_switch_activated_date.isoformat()
                    if self._kill_switch_activated_date else None
                ),
                consecutive_losses=self._consecutive_losses,
                last_loss_time=(
                    self._last_loss_time.isoformat() if self._last_loss_time else None
                ),
                pnl_window_json=json.dumps(self._pnl_tracker.to_state()),
            )
        except Exception as e:
            logger.error(
                "FAILED to persist risk state for %s: %s — a restart would lose "
                "the current halt/loss-streak state.", self._account_id, e,
            )

    # ── Kill Switch ───────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "Manual"):
        """Halt all trading."""
        self._kill_switch = True
        self._kill_switch_reason = reason
        self._kill_switch_activated_date = datetime.utcnow().date()
        logger.critical("KILL SWITCH: %s", reason)
        self._persist_state()

    def deactivate_kill_switch(self):
        """Resume trading."""
        self._kill_switch = False
        self._kill_switch_reason = ""
        self._kill_switch_activated_date = None
        logger.info("Kill switch deactivated")
        self._persist_state()

    def _check_kill_switch_auto_recovery(self):
        """Auto-deactivate kill switch on new trading day.

        If the kill switch was activated on a previous calendar day (UTC),
        it's automatically reset. This allows the system to start fresh
        each trading session while still protecting within a single day.
        """
        if not self._kill_switch:
            return
        if self._kill_switch_activated_date is None:
            return

        today = datetime.utcnow().date()
        if today > self._kill_switch_activated_date:
            old_reason = self._kill_switch_reason
            self._kill_switch = False
            self._kill_switch_reason = ""
            self._kill_switch_activated_date = None
            # Reset daily PnL tracker on new day recovery
            self._pnl_tracker.reset_daily()
            logger.info(
                "Kill switch auto-recovered (was: %s)", old_reason
            )
            # Auto-recovery mutates the halt state, so it must be written
            # too — otherwise the next process would restore the stale halt.
            self._persist_state()

    @property
    def is_kill_switch_active(self) -> bool:
        return self._kill_switch

    # ── Trade Result Tracking ─────────────────────────────────────────

    def record_trade_result(self, pnl: float, ticker: str = ""):
        """Record a completed trade result for consecutive loss tracking.

        Args:
            pnl: Profit/loss of the trade (negative = loss)
            ticker: Ticker symbol
        """
        self._trade_results.append({
            "pnl": pnl,
            "ticker": ticker,
            "timestamp": datetime.utcnow(),
        })

        # Feed per-period PnL tracker
        self._pnl_tracker.record(pnl)

        if pnl < 0:
            self._consecutive_losses += 1
            self._last_loss_time = datetime.utcnow()
        else:
            self._consecutive_losses = 0

        # Persist immediately: this is the record that decides whether the
        # NEXT decision (in a different process, or a different graph
        # instance) sees the loss streak and the drawdown at all.
        self._persist_state()

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current risk controller state."""
        drawdowns = self._pnl_tracker.get_drawdowns(1.0)  # relative to equity
        return {
            "kill_switch": self._kill_switch,
            "kill_switch_reason": self._kill_switch_reason,
            "kill_switch_date": str(self._kill_switch_activated_date) if self._kill_switch_activated_date else None,
            "consecutive_losses": self._consecutive_losses,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_position_pct": self.max_position_pct,
            "max_concurrent_positions": self.max_concurrent_positions,
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "total_trades_recorded": len(self._trade_results),
            "pnl_daily": self._pnl_tracker.daily_pnl,
            "pnl_weekly": self._pnl_tracker.weekly_pnl,
            "pnl_monthly": self._pnl_tracker.monthly_pnl,
        }


# ── Per-Period PnL Tracker ────────────────────────────────────────────

class _PnLTracker:
    """Tracks realized PnL per time period for accurate drawdown comparison.

    Maintains rolling windows:
    - daily: trades from today (UTC)
    - weekly: trades from last 7 calendar days
    - monthly: trades from last 30 calendar days
    """

    def __init__(self):
        self._trades: List[Dict] = []  # {"pnl": float, "timestamp": datetime}
        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0
        self._monthly_pnl = 0.0
        self._last_cleanup: Optional[date] = None

    def record(self, pnl: float):
        """Record a trade result."""
        now = datetime.utcnow()
        self._trades.append({"pnl": pnl, "timestamp": now})
        self._daily_pnl += pnl
        self._weekly_pnl += pnl
        self._monthly_pnl += pnl
        self._cleanup_old_trades()

    def _cleanup_old_trades(self):
        """Remove expired trades and recalculate per-period PnL."""
        now = datetime.utcnow()
        today = now.date()

        # Only cleanup once per minute to avoid overhead
        if self._last_cleanup == today:
            return
        self._last_cleanup = today

        # Recalculate from scratch
        daily_cutoff = datetime.combine(today, datetime.min.time())
        weekly_cutoff = now - timedelta(days=7)
        monthly_cutoff = now - timedelta(days=30)

        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0
        self._monthly_pnl = 0.0

        active_trades = []
        for t in self._trades:
            ts = t["timestamp"]
            if ts < monthly_cutoff:
                continue  # Drop trades older than 30 days
            active_trades.append(t)

            if ts >= daily_cutoff:
                self._daily_pnl += t["pnl"]
            if ts >= weekly_cutoff:
                self._weekly_pnl += t["pnl"]
            self._monthly_pnl += t["pnl"]

        self._trades = active_trades

    def get_drawdowns(self, total_equity: float) -> Dict[str, float]:
        """Get per-period drawdown as fraction of equity.

        Returns dict: {"daily": 0.03, "weekly": 0.05, ...}
        Only includes periods with negative PnL (actual drawdown).
        """
        if total_equity <= 0:
            return {}

        self._cleanup_old_trades()

        result = {}
        if self._daily_pnl < 0:
            result["daily"] = abs(self._daily_pnl) / total_equity
        if self._weekly_pnl < 0:
            result["weekly"] = abs(self._weekly_pnl) / total_equity
        if self._monthly_pnl < 0:
            result["monthly"] = abs(self._monthly_pnl) / total_equity

        return result

    def reset_daily(self):
        """Reset daily PnL counter (called on new trading day)."""
        self._daily_pnl = 0.0

    # ── Persistence ───────────────────────────────────────────────────
    # The rolling window IS the drawdown trigger: without it, every new
    # RiskController starts from zero realized PnL and the daily/weekly
    # loss limits can never be reached, no matter how much was actually
    # lost. Persisting the kill-switch flag alone would therefore fix the
    # symptom while leaving the trigger permanently disarmed.

    def to_state(self) -> List[Dict[str, Any]]:
        """Serialize the rolling trade window (JSON-safe)."""
        self._cleanup_old_trades()
        return [
            {"pnl": t["pnl"], "timestamp": t["timestamp"].isoformat()}
            for t in self._trades
        ]

    def load_state(self, rows: List[Dict[str, Any]]) -> None:
        """Restore a previously serialized window and recompute totals."""
        restored = []
        for r in rows or []:
            try:
                ts = r["timestamp"]
                restored.append({
                    "pnl": float(r["pnl"]),
                    "timestamp": datetime.fromisoformat(ts) if isinstance(ts, str) else ts,
                })
            except (KeyError, TypeError, ValueError):
                continue  # skip malformed rows rather than losing the whole window
        self._trades = restored
        # Force a recompute of the period totals from the restored rows.
        self._last_cleanup = None
        self._cleanup_old_trades()

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def weekly_pnl(self) -> float:
        return self._weekly_pnl

    @property
    def monthly_pnl(self) -> float:
        return self._monthly_pnl
