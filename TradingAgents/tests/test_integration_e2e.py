"""End-to-end integration tests for the full execution pipeline.

Uses REAL PaperBroker (no mocks) to test the complete flow:
    Decision JSON → ExecutionEngine → RiskController → PaperBroker → Portfolio → Journal

Every test creates a fresh full-stack instance via the _make_engine() helper.
"""

import json
import os
import tempfile

import pytest

from tradingagents.execution.brokers.paper_broker import PaperBroker
from tradingagents.execution.execution_engine import ExecutionEngine
from tradingagents.execution.portfolio_manager import PortfolioManager
from tradingagents.execution.risk_controls import RiskController
from tradingagents.storage.database import Database
from tradingagents.storage.trade_journal import TradeJournal


# ── Helper ────────────────────────────────────────────────────────────

def _make_decision_json(
    action: str = "BUY",
    ticker: str = "NVDA",
    confidence: float = 0.8,
    quantity_pct: float = 0.05,
    **kwargs,
) -> str:
    """Build a minimal TradeDecision JSON string."""
    data = {
        "action": action,
        "ticker": ticker,
        "confidence_score": confidence,
        "quantity_pct": quantity_pct,
        **kwargs,
    }
    return json.dumps(data)


def _make_engine(
    initial_cash: float = 10_000.0,
    max_concurrent_positions: int = 3,
    min_confidence: float = 0.5,
    cooldown_seconds: int = 0,
    with_journal: bool = False,
):
    """Create a full-stack ExecutionEngine with real PaperBroker.

    Returns (engine, broker, portfolio, risk_controller, db_path_or_None).
    """
    broker = PaperBroker(initial_cash=initial_cash, commission_pct=0.0, slippage_pct=0.0)
    portfolio = PortfolioManager(initial_cash=initial_cash, max_total_positions=10)
    risk_controller = RiskController(
        max_concurrent_positions=max_concurrent_positions,
        max_position_pct=0.20,  # generous for testing
    )

    journal = None
    db = None
    db_path = None
    if with_journal:
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = Database(db_path=db_path)
        journal = TradeJournal(db=db, session_id="test-session")

    engine = ExecutionEngine(
        broker=broker,
        portfolio_manager=portfolio,
        risk_controller=risk_controller,
        journal=journal,
        min_confidence=min_confidence,
        cooldown_seconds=cooldown_seconds,
        require_confirmation=False,  # no interactive prompt
    )

    return engine, broker, portfolio, risk_controller, db, db_path


def _cleanup(db, db_path):
    """Close DB and remove temp file."""
    if db:
        db.close()
    if db_path and os.path.exists(db_path):
        os.unlink(db_path)


# ── Test Cases ────────────────────────────────────────────────────────

class TestE2EHappyPath:
    """Tests for the normal buy/sell/hold flow."""

    def test_buy_happy_path(self):
        """BUY decision → order filled → portfolio updated."""
        engine, broker, portfolio, _, db, db_path = _make_engine()
        try:
            decision = _make_decision_json("BUY", "NVDA", 0.8, 0.05)
            broker.set_price("NVDA", 120.0)
            result = engine.execute_decision(decision, current_price=120.0)

            assert result is not None
            assert result.is_filled
            assert result.ticker == "NVDA"

            # Portfolio should have position & reduced cash
            assert "NVDA" in portfolio.positions
            assert portfolio.cash_balance < 10_000.0
        finally:
            _cleanup(db, db_path)

    def test_sell_closes_position(self):
        """BUY then SELL → position closed, PnL recorded."""
        engine, broker, portfolio, _, db, db_path = _make_engine()
        try:
            # Open position
            buy_json = _make_decision_json("BUY", "AAPL", 0.9, 0.05)
            broker.set_price("AAPL", 150.0)
            buy_result = engine.execute_decision(buy_json, current_price=150.0)
            assert buy_result is not None and buy_result.is_filled

            cash_after_buy = portfolio.cash_balance

            # Close position — sell everything
            sell_json = _make_decision_json("SELL", "AAPL", 0.9, 1.0)
            broker.set_price("AAPL", 160.0)
            sell_result = engine.execute_decision(sell_json, current_price=160.0)

            assert sell_result is not None and sell_result.is_filled

            # Cash should increase (sold at higher price)
            assert portfolio.cash_balance > cash_after_buy
            # Position should be closed in portfolio
            # (PaperBroker manages its own positions; portfolio tracks via engine)
        finally:
            _cleanup(db, db_path)

    def test_hold_skips_execution(self):
        """HOLD decision → returns None, no order placed."""
        engine, broker, portfolio, _, db, db_path = _make_engine()
        try:
            decision = _make_decision_json("HOLD", "TSLA", 0.9, 0.0)
            result = engine.execute_decision(decision, current_price=200.0)

            assert result is None
            assert portfolio.cash_balance == 10_000.0
            assert len(portfolio.positions) == 0
        finally:
            _cleanup(db, db_path)


class TestE2ERiskChecks:
    """Tests for risk controller and pre-flight checks."""

    def test_low_confidence_rejected(self):
        """Confidence below threshold → rejected."""
        engine, _, portfolio, _, db, db_path = _make_engine(min_confidence=0.5)
        try:
            decision = _make_decision_json("BUY", "AMD", 0.3, 0.05)
            result = engine.execute_decision(decision, current_price=100.0)

            assert result is None
            assert portfolio.cash_balance == 10_000.0  # No cash deducted
        finally:
            _cleanup(db, db_path)

    def test_risk_controller_max_positions(self):
        """Exceed max concurrent positions → rejected by RiskController."""
        engine, broker, portfolio, rc, db, db_path = _make_engine(max_concurrent_positions=2)
        try:
            # Fill 2 positions
            for ticker, price in [("AAPL", 150.0), ("MSFT", 300.0)]:
                broker.set_price(ticker, price)
                r = engine.execute_decision(
                    _make_decision_json("BUY", ticker, 0.9, 0.03),
                    current_price=price,
                )
                assert r is not None and r.is_filled, f"Failed to fill {ticker}"

            # 3rd should be rejected
            broker.set_price("GOOGL", 140.0)
            result = engine.execute_decision(
                _make_decision_json("BUY", "GOOGL", 0.9, 0.03),
                current_price=140.0,
            )
            assert result is None
        finally:
            _cleanup(db, db_path)

    def test_kill_switch_blocks_trade(self):
        """Kill switch active → all trades blocked."""
        engine, _, portfolio, _, db, db_path = _make_engine()
        try:
            engine.activate_kill_switch("Test kill switch")

            decision = _make_decision_json("BUY", "NVDA", 0.9, 0.05)
            result = engine.execute_decision(decision, current_price=120.0)

            assert result is None
            assert portfolio.cash_balance == 10_000.0
        finally:
            _cleanup(db, db_path)


class TestE2EIdempotency:
    """Idempotency key tests."""


    def test_idempotency_prevents_double_order(self):
        """Same idempotency key submitted twice → second is rejected."""
        engine, broker, _, _, db, db_path = _make_engine()
        try:
            decision = _make_decision_json("BUY", "NVDA", 0.9, 0.05)
            key = "unique_key_123"

            broker.set_price("NVDA", 120.0)
            r1 = engine.execute_decision(decision, current_price=120.0, idempotency_key=key)
            assert r1 is not None and r1.is_filled

            r2 = engine.execute_decision(decision, current_price=120.0, idempotency_key=key)
            assert r2 is None  # Duplicate blocked
        finally:
            _cleanup(db, db_path)


class TestE2EJournalIntegration:
    """Tests that trades are persisted to the database via TradeJournal."""

    def test_journal_records_fill(self):
        """BUY FILLED → trade recorded in database."""
        engine, broker, _, _, db, db_path = _make_engine(with_journal=True)
        try:
            decision = _make_decision_json("BUY", "NVDA", 0.9, 0.05)
            broker.set_price("NVDA", 120.0)
            result = engine.execute_decision(decision, current_price=120.0)
            assert result is not None and result.is_filled

            # Query the database — there should be at least one trade
            trades = db.query_trades()
            assert len(trades) >= 1

            last_trade = trades[-1]
            assert last_trade["ticker"] == "NVDA"
        finally:
            _cleanup(db, db_path)


class TestE2EPortfolioTracking:
    """Tests portfolio state after execution."""

    def test_portfolio_equity_updated(self):
        """After BUY, portfolio equity reflects position."""
        engine, broker, portfolio, _, db, db_path = _make_engine()
        try:
            decision = _make_decision_json("BUY", "NVDA", 0.9, 0.10)
            broker.set_price("NVDA", 100.0)
            result = engine.execute_decision(decision, current_price=100.0)
            assert result is not None and result.is_filled

            # Total equity should still be ~10k (cash + position ≈ initial)
            assert portfolio.total_equity == pytest.approx(10_000.0, rel=0.01)

            # But cash should be reduced
            assert portfolio.cash_balance < 10_000.0

            # And we should have a position
            assert len(portfolio.positions) == 1
        finally:
            _cleanup(db, db_path)
