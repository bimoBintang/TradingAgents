"""Trade journal for logging decisions, fills, rejections, and analytics.

Built on top of Database. ALL methods wrap in try/except — journal
failure must NEVER interrupt trading execution.
"""

import csv
import json
import math
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

from tradingagents.storage.database import Database

logger = logging.getLogger(__name__)


class TradeJournal:
    """High-level trade journal with performance analytics.

    All public methods are fault-tolerant: they log warnings on failure
    but never raise exceptions. Journal failure must not halt trading.

    Usage:
        journal = TradeJournal(db, session_id="abc-123")
        journal.log_decision(decision, verdict)
        journal.log_fill(order_result)
        report = journal.get_performance_report()
    """

    def __init__(
        self,
        db: Database,
        session_id: str,
        risk_free_rate_annual: float = 0.05,
    ):
        """Initialize trade journal.

        Args:
            db: Database instance
            session_id: Unique session identifier
            risk_free_rate_annual: Annual risk-free rate for Sharpe ratio
        """
        self.db = db
        self.session_id = session_id
        self.risk_free_rate_annual = risk_free_rate_annual

    # ── Logging Methods (fault-tolerant) ──────────────────────────────

    def log_decision(
        self,
        decision,
        risk_verdict=None,
        agent_reports: Optional[dict] = None,
    ) -> Optional[str]:
        """Log a trade decision and risk verdict.

        Args:
            decision: TradeDecision object
            risk_verdict: RiskVerdict object (optional)
            agent_reports: Dict of analyst outputs (optional)

        Returns:
            trade_id if a corresponding trade was created, else None
        """
        try:
            now = datetime.utcnow().isoformat()

            # Build decision record
            decision_data = {
                "ticker": decision.ticker,
                "action": decision.action.value if hasattr(decision.action, 'value') else str(decision.action),
                "confidence_score": decision.confidence_score,
                "risk_score": risk_verdict.risk_score if risk_verdict else None,
                "parsed_decision_json": decision.model_dump_json() if hasattr(decision, 'model_dump_json') else json.dumps(str(decision)),
                "risk_verdict_json": json.dumps({
                    "approved": risk_verdict.approved,
                    "rejection_reason": risk_verdict.rejection_reason,
                    "risk_score": risk_verdict.risk_score,
                    "warnings": risk_verdict.warnings,
                }) if risk_verdict else None,
                "agent_reports_json": json.dumps(agent_reports) if agent_reports else None,
                "session_id": self.session_id,
                "timestamp": now,
            }

            self.db.insert_decision(decision_data)
            return None

        except Exception as e:
            logger.warning(f"[TradeJournal] log_decision failed: {e}")
            return None

    def log_fill(self, order_result, realized_pnl: Optional[float] = None) -> None:
        """Log a filled order — upsert into trades table.

        Args:
            order_result: OrderResult object
            realized_pnl: Realized P&L if closing position
        """
        try:
            now = datetime.utcnow().isoformat()
            trade_id = order_result.idempotency_key or order_result.order_id or f"fill_{now}"

            trade_data = {
                "id": trade_id,
                "ticker": order_result.ticker,
                "action": order_result.side.value if hasattr(order_result.side, 'value') else str(order_result.side),
                "requested_qty": order_result.requested_quantity if hasattr(order_result, 'requested_quantity') else None,
                "filled_qty": order_result.filled_quantity,
                "remaining_qty": order_result.remaining_quantity,
                "fill_price": order_result.filled_price,
                "average_fill_price": order_result.average_fill_price,
                "fill_time": now,
                "realized_pnl": realized_pnl,
                "status": order_result.status.value if hasattr(order_result.status, 'value') else str(order_result.status),
                "broker": order_result.broker if hasattr(order_result, 'broker') else None,
                "session_id": self.session_id,
                "created_at": now,
            }

            self.db.insert_trade(trade_data)

        except Exception as e:
            logger.warning(f"[TradeJournal] log_fill failed: {e}")

    def log_rejection(self, decision, risk_verdict) -> None:
        """Log a rejected trade decision.

        Args:
            decision: TradeDecision that was rejected
            risk_verdict: RiskVerdict with rejection details
        """
        try:
            now = datetime.utcnow().isoformat()
            trade_id = f"rejected_{decision.ticker}_{now}"

            # Determine rejection code from reason
            rejection_code = self._extract_rejection_code(risk_verdict.rejection_reason)

            trade_data = {
                "id": trade_id,
                "ticker": decision.ticker,
                "action": decision.action.value if hasattr(decision.action, 'value') else str(decision.action),
                "requested_qty": None,
                "filled_qty": None,
                "remaining_qty": None,
                "fill_price": None,
                "average_fill_price": None,
                "fill_time": None,
                "realized_pnl": None,
                "status": "REJECTED",
                "broker": None,
                "rejection_code": rejection_code,
                "rejection_reason": risk_verdict.rejection_reason,
                "risk_score": risk_verdict.risk_score,
                "confidence_score": decision.confidence_score,
                "session_id": self.session_id,
                "created_at": now,
            }

            self.db.insert_trade(trade_data)

        except Exception as e:
            logger.warning(f"[TradeJournal] log_rejection failed: {e}")

    def log_reflection(
        self, agent_name: str, ticker: Optional[str], content: str
    ) -> None:
        """Log a reflection.

        Args:
            agent_name: Agent that produced the reflection
            ticker: Ticker being analyzed
            content: Reflection text
        """
        try:
            self.db.insert_reflection(agent_name, ticker, self.session_id, content)
        except Exception as e:
            logger.warning(f"[TradeJournal] log_reflection failed: {e}")

    def snapshot_portfolio(self, portfolio) -> None:
        """Save a portfolio snapshot.

        Args:
            portfolio: PortfolioState object
        """
        try:
            now = datetime.utcnow().isoformat()

            # Serialize open positions
            positions_json = json.dumps([
                {
                    "ticker": p.ticker,
                    "side": p.side.value if hasattr(p.side, 'value') else str(p.side),
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                }
                for p in (portfolio.open_positions or [])
            ])

            snapshot_data = {
                "timestamp": now,
                "cash": portfolio.cash_balance,
                "total_equity": portfolio.total_equity,
                "open_positions_json": positions_json,
                "unrealized_pnl": sum(
                    p.unrealized_pnl for p in (portfolio.open_positions or [])
                ) if portfolio.open_positions else 0.0,
                "realized_pnl": portfolio.total_pnl if hasattr(portfolio, 'total_pnl') else None,
                "drawdown_pct": portfolio.max_drawdown_pct,
                "session_id": self.session_id,
            }

            self.db.snapshot_portfolio(snapshot_data)

        except Exception as e:
            logger.warning(f"[TradeJournal] snapshot_portfolio failed: {e}")

    # ── Query Methods ─────────────────────────────────────────────────

    def get_trades(
        self,
        ticker: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        action: Optional[str] = None,
        min_pnl: Optional[float] = None,
    ) -> List[dict]:
        """Query trades with filters."""
        try:
            return self.db.query_trades(ticker, start_date, end_date, action, min_pnl)
        except Exception as e:
            logger.warning(f"[TradeJournal] get_trades failed: {e}")
            return []

    def get_rejection_stats(self) -> Dict[str, int]:
        """Get rejection count by code."""
        try:
            return self.db.query_rejection_stats()
        except Exception as e:
            logger.warning(f"[TradeJournal] get_rejection_stats failed: {e}")
            return {}

    def get_equity_curve(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[dict]:
        """Get equity curve sorted ascending by timestamp."""
        try:
            return self.db.query_equity_curve(start_date, end_date)
        except Exception as e:
            logger.warning(f"[TradeJournal] get_equity_curve failed: {e}")
            return []

    def get_similar_trades(self, ticker: str, action: str) -> List[dict]:
        """Query past trades for same ticker + action."""
        try:
            return self.db.query_trades(ticker=ticker, action=action)
        except Exception as e:
            logger.warning(f"[TradeJournal] get_similar_trades failed: {e}")
            return []

    def get_performance_report(self) -> dict:
        """Generate performance analytics report.

        Returns:
            Dict with win_rate, profit_factor, sharpe_ratio, max_drawdown,
            total_trades, avg_pnl, best_trade, worst_trade
        """
        try:
            trades = self.db.query_trades()

            # Filter to filled trades with PnL
            filled = [t for t in trades if t.get("realized_pnl") is not None
                      and t.get("status") not in ("REJECTED",)]

            if not filled:
                return {
                    "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                    "sharpe_ratio": 0.0, "max_drawdown": 0.0, "avg_pnl": 0.0,
                    "best_trade": 0.0, "worst_trade": 0.0,
                }

            pnls = [t["realized_pnl"] for t in filled]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            total_trades = len(filled)
            win_rate = len(wins) / total_trades if total_trades else 0.0
            avg_pnl = sum(pnls) / total_trades

            # Profit factor
            gross_profit = sum(wins) if wins else 0.0
            gross_loss = abs(sum(losses)) if losses else 0.0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

            # Sharpe ratio
            if len(pnls) > 1:
                mean_return = sum(pnls) / len(pnls)
                std_return = math.sqrt(sum((p - mean_return) ** 2 for p in pnls) / (len(pnls) - 1))
                # Annualize: assume ~252 trading days
                daily_rf = self.risk_free_rate_annual / 252
                sharpe = (mean_return - daily_rf) / std_return if std_return > 0 else 0.0
            else:
                sharpe = 0.0

            # Max drawdown from equity curve
            equity_curve = self.db.query_equity_curve()
            max_drawdown = 0.0
            if equity_curve:
                peak = equity_curve[0].get("total_equity", 0)
                for snap in equity_curve:
                    equity = snap.get("total_equity", 0)
                    if equity > peak:
                        peak = equity
                    dd = (peak - equity) / peak if peak > 0 else 0
                    max_drawdown = max(max_drawdown, dd)

            return {
                "total_trades": total_trades,
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 4),
                "sharpe_ratio": round(sharpe, 4),
                "max_drawdown": round(max_drawdown, 4),
                "avg_pnl": round(avg_pnl, 2),
                "best_trade": round(max(pnls), 2),
                "worst_trade": round(min(pnls), 2),
            }

        except Exception as e:
            logger.warning(f"[TradeJournal] get_performance_report failed: {e}")
            return {}

    # ── Export ─────────────────────────────────────────────────────────

    def export_csv(self, filepath: str) -> None:
        """Export trades to CSV file.

        This is the ONE method that CAN raise IOError.

        Args:
            filepath: Path to output CSV file

        Raises:
            IOError: If file cannot be written
        """
        trades = self.db.query_trades()
        if not trades:
            logger.info("No trades to export")
            return

        fieldnames = list(trades[0].keys())
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(trades)

        logger.info("Exported %d trades to %s", len(trades), filepath)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _extract_rejection_code(reason: str) -> str:
        """Extract a short rejection code from the reason string."""
        if not reason:
            return "unknown"
        reason_lower = reason.lower()
        if "kill switch" in reason_lower:
            return "kill_switch"
        if "drawdown" in reason_lower:
            return "max_drawdown"
        if "cooldown" in reason_lower or "consecutive" in reason_lower:
            return "consecutive_loss_cooldown"
        if "max positions" in reason_lower:
            return "max_positions"
        if "correlation" in reason_lower:
            return "correlation_limit"
        if "confidence" in reason_lower:
            return "low_confidence"
        if "hold" in reason_lower:
            return "hold_action"
        return "other"
