"""Tests for Futures Trading Support.

Validates that all new futures-related features (leverage, margin mode,
position side, risk controls) work correctly AND that existing spot
functionality remains backward compatible.
"""

import unittest
from unittest.mock import MagicMock, patch

from tradingagents.execution.order_models import (
    TradeAction,
    TradeDecision,
    OrderSide,
    OrderType,
    PositionInfo,
    PositionSide,
    MarginType,
    MarketType,
    PortfolioState,
)
from tradingagents.execution.risk_controls import RiskController, RiskVerdict


# ── Helper: minimal TradeDecision factory ─────────────────────────────

def _make_decision(**kwargs):
    defaults = dict(
        action=TradeAction.BUY,
        ticker="BTC/USDT",
        confidence_score=0.8,
        quantity_pct=0.10,
    )
    defaults.update(kwargs)
    return TradeDecision(**defaults)


def _make_portfolio(**kwargs):
    defaults = dict(
        cash_balance=10_000.0,
        total_equity=10_000.0,
        open_positions=[],
    )
    defaults.update(kwargs)
    return PortfolioState(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# 1. Order Models — New Enums & Fields
# ═══════════════════════════════════════════════════════════════════════

class TestMarketTypeEnum(unittest.TestCase):
    def test_values(self):
        self.assertEqual(MarketType.SPOT, "spot")
        self.assertEqual(MarketType.FUTURES, "future")

    def test_position_side_values(self):
        self.assertEqual(PositionSide.LONG, "LONG")
        self.assertEqual(PositionSide.SHORT, "SHORT")

    def test_margin_type_values(self):
        self.assertEqual(MarginType.ISOLATED, "isolated")
        self.assertEqual(MarginType.CROSS, "cross")


class TestTradeDecisionFuturesFields(unittest.TestCase):
    def test_default_leverage_is_1(self):
        """Default leverage=1 means spot-equivalent — no futures setup needed."""
        d = _make_decision()
        self.assertEqual(d.leverage, 1)
        self.assertEqual(d.position_side, PositionSide.LONG)
        self.assertEqual(d.margin_type, MarginType.ISOLATED)

    def test_leverage_field_with_value(self):
        d = _make_decision(leverage=10)
        self.assertEqual(d.leverage, 10)

    def test_short_position_side(self):
        d = _make_decision(position_side=PositionSide.SHORT)
        self.assertEqual(d.position_side, PositionSide.SHORT)

    def test_cross_margin(self):
        d = _make_decision(margin_type=MarginType.CROSS)
        self.assertEqual(d.margin_type, MarginType.CROSS)


class TestPositionInfoFuturesFields(unittest.TestCase):
    def test_default_futures_fields(self):
        p = PositionInfo(
            ticker="BTC/USDT",
            side=OrderSide.BUY,
            quantity=0.5,
            entry_price=65000.0,
            current_price=66000.0,
            entry_timestamp="2026-01-01T00:00:00",
        )
        self.assertEqual(p.position_side, PositionSide.LONG)
        self.assertEqual(p.leverage, 1)
        self.assertIsNone(p.liquidation_price)
        self.assertEqual(p.margin_type, MarginType.ISOLATED)

    def test_futures_position(self):
        p = PositionInfo(
            ticker="BTC/USDT",
            side=OrderSide.SELL,
            quantity=1.0,
            entry_price=65000.0,
            current_price=63000.0,
            entry_timestamp="2026-01-01T00:00:00",
            position_side=PositionSide.SHORT,
            leverage=20,
            liquidation_price=68000.0,
            margin_type=MarginType.CROSS,
        )
        self.assertEqual(p.position_side, PositionSide.SHORT)
        self.assertEqual(p.leverage, 20)
        self.assertEqual(p.liquidation_price, 68000.0)
        self.assertEqual(p.margin_type, MarginType.CROSS)


# ═══════════════════════════════════════════════════════════════════════
# 2. CcxtBroker — Futures methods
# ═══════════════════════════════════════════════════════════════════════

class TestCcxtBrokerFutures(unittest.TestCase):
    """Mock-based tests for CcxtBroker futures methods."""

    def _make_broker(self, market_type="spot"):
        """Create a CcxtBroker with mocked exchange."""
        with patch("tradingagents.execution.brokers.ccxt_broker.ccxt") as mock_ccxt:
            mock_exchange_class = MagicMock()
            mock_exchange_instance = MagicMock()
            mock_exchange_class.return_value = mock_exchange_instance
            mock_ccxt.exchanges = ["binance"]
            setattr(mock_ccxt, "binance", mock_exchange_class)

            from tradingagents.execution.brokers.ccxt_broker import CcxtBroker
            broker = CcxtBroker(
                exchange_id="binance",
                market_type=market_type,
                sandbox=False,
            )
            return broker, mock_exchange_instance

    def test_market_type_config_spot(self):
        broker, _ = self._make_broker("spot")
        self.assertEqual(broker.market_type, "spot")

    def test_market_type_config_future(self):
        broker, _ = self._make_broker("future")
        self.assertEqual(broker.market_type, "future")

    def test_set_leverage_skipped_for_spot(self):
        broker, mock_ex = self._make_broker("spot")
        result = broker.set_leverage("BTC/USDT", 10)
        self.assertFalse(result)
        mock_ex.set_leverage.assert_not_called()

    def test_set_leverage_called_for_futures(self):
        broker, mock_ex = self._make_broker("future")
        result = broker.set_leverage("BTC/USDT", 10)
        self.assertTrue(result)
        mock_ex.set_leverage.assert_called_once_with(10, "BTC/USDT")

    def test_set_margin_mode_skipped_for_spot(self):
        broker, mock_ex = self._make_broker("spot")
        result = broker.set_margin_mode("BTC/USDT", "isolated")
        self.assertFalse(result)
        mock_ex.set_margin_mode.assert_not_called()

    def test_set_margin_mode_called_for_futures(self):
        broker, mock_ex = self._make_broker("future")
        result = broker.set_margin_mode("BTC/USDT", "cross")
        self.assertTrue(result)
        mock_ex.set_margin_mode.assert_called_once_with("cross", "BTC/USDT")

    def test_place_order_includes_position_side_futures(self):
        broker, mock_ex = self._make_broker("future")
        mock_ex.create_order.return_value = {
            "id": "order123",
            "filled": 1.0,
            "remaining": 0.0,
            "average": 65000.0,
            "status": "closed",
            "fee": {"cost": 0.5},
        }
        result = broker.place_order(
            ticker="BTC/USDT",
            side=OrderSide.BUY,
            quantity=1.0,
            position_side="LONG",
        )
        call_kwargs = mock_ex.create_order.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        # Params are passed via `params=` argument
        self.assertIn("positionSide", params)
        self.assertEqual(params["positionSide"], "LONG")


# ═══════════════════════════════════════════════════════════════════════
# 3. Risk Controls — Leverage
# ═══════════════════════════════════════════════════════════════════════

class TestRiskControllerLeverage(unittest.TestCase):

    def test_leverage_within_limit_approved(self):
        rc = RiskController(max_leverage=10)
        decision = _make_decision(leverage=5)
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertTrue(verdict.approved)

    def test_leverage_exceeds_cap_rejected(self):
        rc = RiskController(max_leverage=10)
        decision = _make_decision(leverage=50)
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertFalse(verdict.approved)
        self.assertIn("50x", verdict.rejection_reason)
        self.assertIn("10x", verdict.rejection_reason)

    def test_liquidation_proximity_warning_high(self):
        """25x leverage → 4% liquidation distance → should trigger warning."""
        rc = RiskController(max_leverage=25)
        decision = _make_decision(leverage=25)
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertTrue(verdict.approved)
        warning_found = any("liquidation" in w.lower() for w in verdict.warnings)
        self.assertTrue(warning_found, f"Expected liquidation warning in {verdict.warnings}")

    def test_liquidation_no_warning_for_spot(self):
        """Leverage=1 (spot) should produce no liquidation warnings."""
        rc = RiskController(max_leverage=10)
        decision = _make_decision(leverage=1)
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertTrue(verdict.approved)
        liq_warnings = [w for w in verdict.warnings if "liquidation" in w.lower()]
        self.assertEqual(len(liq_warnings), 0)

    def test_leverage_adjusted_position_sizing(self):
        """With 10x leverage, max 10% position → effective max 1%."""
        rc = RiskController(max_position_pct=0.10, max_leverage=20)
        decision = _make_decision(leverage=10, quantity_pct=0.10)
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertTrue(verdict.approved)
        # Position should be adjusted: 10% / 10x = 1%
        adjusted = verdict.adjusted_decision
        self.assertAlmostEqual(adjusted.quantity_pct, 0.01, places=4)

    def test_backward_compat_spot_no_leverage(self):
        """Default decision (leverage=1) should behave identically to before."""
        rc = RiskController(max_leverage=10)
        decision = _make_decision()  # leverage=1 by default
        portfolio = _make_portfolio()
        verdict = rc.evaluate(decision, portfolio)
        self.assertTrue(verdict.approved)
        self.assertEqual(verdict.adjusted_decision.leverage, 1)


# ═══════════════════════════════════════════════════════════════════════
# 4. Default Config
# ═══════════════════════════════════════════════════════════════════════

class TestDefaultConfigFutures(unittest.TestCase):
    def test_config_has_futures_fields(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        exec_cfg = DEFAULT_CONFIG["execution"]
        self.assertEqual(exec_cfg["market_type"], "spot")
        self.assertEqual(exec_cfg["leverage"], 1)
        self.assertEqual(exec_cfg["margin_type"], "isolated")
        self.assertEqual(exec_cfg["max_leverage"], 10)


if __name__ == "__main__":
    unittest.main()
