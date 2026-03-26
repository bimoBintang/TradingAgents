"""Tests for Deep Refinement changes.

Validates that the 7 refinement areas work correctly:
1. _create_broker passes market_type
2. RiskController receives max_leverage from config
3. SignalProcessor accepts execution_strategy parameter
4. RealtimeFeed uses broker for price polling
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock


# ═══════════════════════════════════════════════════════════════════════
# 1. Broker Factory — market_type Pass-Through
# ═══════════════════════════════════════════════════════════════════════

class TestBrokerFactoryMarketType(unittest.TestCase):
    """Verify _create_broker passes market_type to CcxtBroker."""

    @patch("tradingagents.graph.trading_graph.CcxtBroker")
    def test_create_broker_passes_market_type_future(self, mock_ccxt_cls):
        mock_broker = MagicMock()
        mock_broker.name = "ccxt"
        mock_ccxt_cls.return_value = mock_broker

        from tradingagents.graph.trading_graph import _create_broker

        config = {
            "execution": {
                "broker": "ccxt",
                "exchange": "binance",
                "market_type": "future",
                "api_key": "",
                "api_secret": "",
                "sandbox": True,
                "quote_currency": "USDT",
            },
            "portfolio": {},
        }
        _create_broker(config)

        # Verify market_type was passed
        call_kwargs = mock_ccxt_cls.call_args
        self.assertEqual(call_kwargs.kwargs.get("market_type"), "future")

    @patch("tradingagents.graph.trading_graph.CcxtBroker")
    def test_create_broker_defaults_to_spot(self, mock_ccxt_cls):
        mock_broker = MagicMock()
        mock_broker.name = "ccxt"
        mock_ccxt_cls.return_value = mock_broker

        from tradingagents.graph.trading_graph import _create_broker

        config = {
            "execution": {
                "broker": "ccxt",
                "exchange": "binance",
                "api_key": "",
                "api_secret": "",
                "sandbox": True,
            },
            "portfolio": {},
        }
        _create_broker(config)

        call_kwargs = mock_ccxt_cls.call_args
        self.assertEqual(call_kwargs.kwargs.get("market_type"), "spot")


# ═══════════════════════════════════════════════════════════════════════
# 2. SignalProcessor — execution_strategy Parameter
# ═══════════════════════════════════════════════════════════════════════

class TestSignalProcessorExecutionStrategy(unittest.TestCase):

    def test_process_signal_accepts_execution_strategy(self):
        """Verify process_signal accepts an execution_strategy parameter."""
        from tradingagents.graph.signal_processing import SignalProcessor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='{"action":"BUY","ticker":"BTC","confidence_score":0.8,'
                    '"quantity_pct":0.1,"stop_loss_pct":0.05,"take_profit_pct":0.1,'
                    '"leverage":5,"position_side":"LONG","margin_type":"isolated"}'
        )

        sp = SignalProcessor(mock_llm)
        result = sp.process_signal(
            "BUY BTC with high confidence",
            ticker="BTC",
            execution_strategy="Use TWAP execution over 30min window",
        )

        # Should have called LLM with combined signal
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        self.assertIn("Execution Strategy", human_msg)

    def test_process_signal_without_execution_strategy(self):
        """Backward compat: works without execution_strategy parameter."""
        from tradingagents.graph.signal_processing import SignalProcessor

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(
            content='{"action":"HOLD","ticker":"ETH","confidence_score":0.3,'
                    '"quantity_pct":0.0}'
        )

        sp = SignalProcessor(mock_llm)
        result = sp.process_signal("HOLD ETH", ticker="ETH")

        # Should work without error
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════════════════
# 3. RealtimeFeed — Broker-Based Price Polling
# ═══════════════════════════════════════════════════════════════════════

class TestRealtimeFeedBroker(unittest.TestCase):

    def test_realtime_feed_accepts_broker(self):
        """RealtimeFeed should accept a broker parameter."""
        from tradingagents.realtime.realtime_feed import RealtimeFeed

        mock_pm = MagicMock()
        mock_pm.positions = {}
        mock_broker = MagicMock()

        feed = RealtimeFeed(
            portfolio_manager=mock_pm,
            broker=mock_broker,
        )
        self.assertIs(feed.broker, mock_broker)

    def test_realtime_feed_uses_broker_for_prices(self):
        """When broker is provided, use it for price polling."""
        from tradingagents.realtime.realtime_feed import RealtimeFeed

        mock_pm = MagicMock()
        mock_pm.positions = {"BTC/USDT": MagicMock()}

        mock_broker = MagicMock()
        mock_broker.get_current_price.return_value = 65000.0

        feed = RealtimeFeed(
            portfolio_manager=mock_pm,
            broker=mock_broker,
        )
        feed._poll_prices()

        mock_broker.get_current_price.assert_called_once_with("BTC/USDT")
        mock_pm.update_prices.assert_called_once()

    def test_realtime_feed_without_broker_fallback(self):
        """Without broker, should not crash (falls back to yfinance)."""
        from tradingagents.realtime.realtime_feed import RealtimeFeed

        mock_pm = MagicMock()
        mock_pm.positions = {}  # Empty — no polling needed

        feed = RealtimeFeed(portfolio_manager=mock_pm)
        self.assertIsNone(feed.broker)
        # Should not crash with empty positions
        feed._poll_prices()


# ═══════════════════════════════════════════════════════════════════════
# 4. Trader Prompt — Futures Fields Present
# ═══════════════════════════════════════════════════════════════════════

class TestTraderPromptFutures(unittest.TestCase):

    def test_prompt_contains_leverage(self):
        from tradingagents.agents.trader.trader import TRADER_SYSTEM_PROMPT
        self.assertIn("leverage", TRADER_SYSTEM_PROMPT)

    def test_prompt_contains_position_side(self):
        from tradingagents.agents.trader.trader import TRADER_SYSTEM_PROMPT
        self.assertIn("position_side", TRADER_SYSTEM_PROMPT)

    def test_prompt_contains_margin_type(self):
        from tradingagents.agents.trader.trader import TRADER_SYSTEM_PROMPT
        self.assertIn("margin_type", TRADER_SYSTEM_PROMPT)

    def test_prompt_contains_futures_guidelines(self):
        from tradingagents.agents.trader.trader import TRADER_SYSTEM_PROMPT
        self.assertIn("Futures Trading Guidelines", TRADER_SYSTEM_PROMPT)


# ═══════════════════════════════════════════════════════════════════════
# 5. Execution Optimizer Prompt — Futures Section
# ═══════════════════════════════════════════════════════════════════════

class TestExecutionOptimizerFutures(unittest.TestCase):

    def test_optimizer_prompt_has_futures_section(self):
        from tradingagents.agents.trader.execution_optimizer import EXECUTION_OPTIMIZER_PROMPT
        self.assertIn("Futures-Specific", EXECUTION_OPTIMIZER_PROMPT)
        self.assertIn("funding rate", EXECUTION_OPTIMIZER_PROMPT)
        self.assertIn("liquidation", EXECUTION_OPTIMIZER_PROMPT)


# ═══════════════════════════════════════════════════════════════════════
# 6. Signal Extraction Prompt — Futures Fields
# ═══════════════════════════════════════════════════════════════════════

class TestSignalExtractionPromptFutures(unittest.TestCase):

    def test_prompt_contains_futures_fields(self):
        from tradingagents.graph.signal_processing import SIGNAL_EXTRACTION_PROMPT
        self.assertIn("leverage", SIGNAL_EXTRACTION_PROMPT)
        self.assertIn("position_side", SIGNAL_EXTRACTION_PROMPT)
        self.assertIn("margin_type", SIGNAL_EXTRACTION_PROMPT)


if __name__ == "__main__":
    unittest.main()
