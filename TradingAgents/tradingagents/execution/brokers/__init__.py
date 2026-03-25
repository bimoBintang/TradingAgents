from .broker_base import BaseBroker, BrokerConnectionError
from .paper_broker import PaperBroker

# Optional imports — only available when extra dependencies are installed
try:
    from .ccxt_broker import CcxtBroker
except ImportError:
    CcxtBroker = None

try:
    from .alpaca_broker import AlpacaBroker, MarketClosedError
except ImportError:
    AlpacaBroker = None
    MarketClosedError = None

__all__ = [
    "BaseBroker",
    "BrokerConnectionError",
    "PaperBroker",
    "CcxtBroker",
    "AlpacaBroker",
]
