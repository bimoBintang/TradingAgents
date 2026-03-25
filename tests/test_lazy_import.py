"""Tests for lazy import of CcxtBroker and AlpacaBroker in trading_graph.py.

Verifies that:
1. Missing ccxt/alpaca raises ImportError with actionable message
2. PaperBroker always works regardless of optional deps
"""

from unittest.mock import patch, MagicMock

import pytest

from tradingagents.graph import trading_graph


class TestLazyImportGuard:

    def test_ccxt_none_raises_import_error(self):
        """Config broker='ccxt' but CcxtBroker is None → ImportError."""
        config = {"execution": {"broker": "ccxt"}, "portfolio": {}}

        with patch.object(trading_graph, "CcxtBroker", None):
            with pytest.raises(ImportError, match=r"pip install tradingagents\[crypto\]"):
                trading_graph._create_broker(config)

    def test_alpaca_none_raises_import_error(self):
        """Config broker='alpaca' but AlpacaBroker is None → ImportError."""
        config = {"execution": {"broker": "alpaca"}, "portfolio": {}}

        with patch.object(trading_graph, "AlpacaBroker", None):
            with pytest.raises(ImportError, match=r"pip install tradingagents\[stocks\]"):
                trading_graph._create_broker(config)

    def test_paper_broker_always_works(self):
        """PaperBroker works even if CcxtBroker and AlpacaBroker are None."""
        config = {"execution": {"broker": "paper"}, "portfolio": {"initial_cash": 5000}}

        with patch.object(trading_graph, "CcxtBroker", None), \
             patch.object(trading_graph, "AlpacaBroker", None):
            broker = trading_graph._create_broker(config)

        assert broker is not None
        assert broker.name == "paper"

    def test_unknown_broker_raises_value_error(self):
        """Unknown broker type raises ValueError."""
        config = {"execution": {"broker": "nonexistent"}, "portfolio": {}}

        with pytest.raises(ValueError, match="Unknown broker type"):
            trading_graph._create_broker(config)
