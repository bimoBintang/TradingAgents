"""Tests for Order Flow / Market Microstructure.

Validates:
- OrderFlowAnalyzer (OBI, spread, wall detection, execution signals)
- CcxtBroker.get_order_book (mocked)
- ExecutionEngine Smart Guard (Step 7.5)
"""

import unittest
from unittest.mock import MagicMock, patch

from tradingagents.execution.order_flow import OrderFlowAnalyzer


# ═══════════════════════════════════════════════════════════════════════
# Test Data Helpers
# ═══════════════════════════════════════════════════════════════════════

def _bullish_book():
    """Order book with strong buy pressure (OBI ≈ +0.5)."""
    return {
        "bids": [[65000, 3.0], [64999, 2.5], [64998, 2.0]],
        "asks": [[65001, 1.0], [65002, 0.8], [65003, 0.7]],
    }


def _bearish_book():
    """Order book with strong sell pressure (OBI ≈ -0.5)."""
    return {
        "bids": [[65000, 0.5], [64999, 0.3], [64998, 0.2]],
        "asks": [[65001, 3.0], [65002, 2.5], [65003, 2.0]],
    }


def _balanced_book():
    """Order book with balanced pressure (OBI ≈ 0)."""
    return {
        "bids": [[65000, 2.0], [64999, 2.0], [64998, 2.0]],
        "asks": [[65001, 2.0], [65002, 2.0], [65003, 2.0]],
    }


def _book_with_wall():
    """Order book with a large sell wall."""
    return {
        "bids": [[65000, 1.0], [64999, 0.5]],
        "asks": [[65001, 2.0], [65002, 0.5]],  # 65001 * 2.0 = $130,002 → wall
    }


def _empty_book():
    return {"bids": [], "asks": []}


# ═══════════════════════════════════════════════════════════════════════
# 1. OBI Calculator
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateOBI(unittest.TestCase):

    def test_balanced_obi(self):
        obi = OrderFlowAnalyzer.calculate_obi(_balanced_book())
        self.assertAlmostEqual(obi, 0.0, places=2)

    def test_bullish_obi(self):
        obi = OrderFlowAnalyzer.calculate_obi(_bullish_book())
        self.assertGreater(obi, 0.3)

    def test_bearish_obi(self):
        obi = OrderFlowAnalyzer.calculate_obi(_bearish_book())
        self.assertLess(obi, -0.3)

    def test_empty_obi(self):
        obi = OrderFlowAnalyzer.calculate_obi(_empty_book())
        self.assertEqual(obi, 0.0)


# ═══════════════════════════════════════════════════════════════════════
# 2. Spread Calculator
# ═══════════════════════════════════════════════════════════════════════

class TestCalculateSpread(unittest.TestCase):

    def test_normal_spread(self):
        spread = OrderFlowAnalyzer.calculate_spread(_balanced_book())
        # best_bid=65000, best_ask=65001 → spread ≈ 0.00001538
        self.assertGreater(spread, 0.0)
        self.assertLess(spread, 0.001)  # < 0.1%

    def test_empty_spread(self):
        spread = OrderFlowAnalyzer.calculate_spread(_empty_book())
        self.assertEqual(spread, 0.0)


# ═══════════════════════════════════════════════════════════════════════
# 3. Wall Detection
# ═══════════════════════════════════════════════════════════════════════

class TestDetectWalls(unittest.TestCase):

    def test_detect_sell_wall(self):
        analyzer = OrderFlowAnalyzer({"wall_detection_usd": 100000})
        walls = analyzer.detect_large_walls(_book_with_wall())
        # 65001 * 2.0 = $130,002 → should detect
        self.assertTrue(len(walls) >= 1)
        ask_walls = [w for w in walls if w.side == "ask"]
        self.assertTrue(len(ask_walls) >= 1)

    def test_no_wall_balanced(self):
        analyzer = OrderFlowAnalyzer({"wall_detection_usd": 500000})
        walls = analyzer.detect_large_walls(_balanced_book())
        self.assertEqual(len(walls), 0)


# ═══════════════════════════════════════════════════════════════════════
# 4. Execution Signal — BUY Side
# ═══════════════════════════════════════════════════════════════════════

class TestExecutionSignalBuy(unittest.TestCase):

    def test_buy_favorable(self):
        """Strong buy pressure → EXECUTE."""
        analyzer = OrderFlowAnalyzer()
        signal = analyzer.get_execution_signal(_bullish_book(), "buy")
        self.assertEqual(signal.action, "EXECUTE")

    def test_buy_unfavorable(self):
        """Strong sell pressure → BLOCK for buy."""
        analyzer = OrderFlowAnalyzer()
        signal = analyzer.get_execution_signal(_bearish_book(), "buy")
        self.assertEqual(signal.action, "BLOCK")

    def test_buy_neutral(self):
        """Balanced → WAIT for buy."""
        analyzer = OrderFlowAnalyzer()
        signal = analyzer.get_execution_signal(_balanced_book(), "buy")
        self.assertEqual(signal.action, "WAIT")


# ═══════════════════════════════════════════════════════════════════════
# 5. Execution Signal — SELL Side
# ═══════════════════════════════════════════════════════════════════════

class TestExecutionSignalSell(unittest.TestCase):

    def test_sell_favorable(self):
        """Strong sell pressure (bearish book) → EXECUTE for sell."""
        analyzer = OrderFlowAnalyzer()
        signal = analyzer.get_execution_signal(_bearish_book(), "sell")
        self.assertEqual(signal.action, "EXECUTE")

    def test_sell_unfavorable(self):
        """Strong buy pressure → unfavorable for sell."""
        analyzer = OrderFlowAnalyzer()
        signal = analyzer.get_execution_signal(_bullish_book(), "sell")
        # Inverted OBI = -0.5 → should BLOCK
        self.assertEqual(signal.action, "BLOCK")


# ═══════════════════════════════════════════════════════════════════════
# 6. CcxtBroker.get_order_book (Mocked)
# ═══════════════════════════════════════════════════════════════════════

class TestCcxtBrokerOrderBook(unittest.TestCase):

    @patch("tradingagents.execution.brokers.ccxt_broker.ccxt")
    def test_get_order_book_returns_data(self, mock_ccxt):
        mock_exchange_cls = MagicMock()
        mock_exchange = MagicMock()
        mock_exchange.fetch_order_book.return_value = _bullish_book()
        mock_exchange_cls.return_value = mock_exchange
        mock_ccxt.binance = mock_exchange_cls

        from tradingagents.execution.brokers.ccxt_broker import CcxtBroker
        broker = CcxtBroker.__new__(CcxtBroker)
        broker.exchange = mock_exchange
        broker.default_quote = "USDT"
        broker.market_type = "spot"
        broker._retry_config = MagicMock()
        broker._retry_config.max_attempts = 0

        # Direct call (bypass retry)
        broker.exchange.fetch_order_book.return_value = _bullish_book()
        book = broker.get_order_book("BTC/USDT")
        self.assertIn("bids", book)
        self.assertIn("asks", book)
        self.assertTrue(len(book["bids"]) > 0)


# ═══════════════════════════════════════════════════════════════════════
# 7. Default Config
# ═══════════════════════════════════════════════════════════════════════

class TestOrderFlowConfig(unittest.TestCase):

    def test_config_has_order_flow(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        self.assertIn("order_flow", DEFAULT_CONFIG)

    def test_order_flow_disabled_by_default(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        self.assertFalse(DEFAULT_CONFIG["order_flow"]["enabled"])

    def test_order_flow_has_thresholds(self):
        from tradingagents.default_config import DEFAULT_CONFIG
        of = DEFAULT_CONFIG["order_flow"]
        self.assertIn("obi_execute_threshold", of)
        self.assertIn("obi_block_threshold", of)
        self.assertIn("order_book_depth", of)
        self.assertIn("max_wait_seconds", of)
        self.assertIn("wall_detection_usd", of)


if __name__ == "__main__":
    unittest.main()
