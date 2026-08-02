from .utils.agent_utils import create_msg_delete
from .utils.agent_states import AgentState, InvestDebateState, RiskDebateState
from .utils.memory import FinancialSituationMemory

from .analysts.fundamentals_analyst import create_fundamentals_analyst
from .analysts.market_analyst import create_market_analyst
from .analysts.news_analyst import create_news_analyst
from .analysts.social_media_analyst import create_social_media_analyst
from .analysts.quant_analyst import create_quant_analyst
from .analysts.onchain_analyst import create_onchain_analyst
from .analysts.macro_geo_analyst import create_macro_geo_analyst
from .analysts.correlation_analyst import create_correlation_analyst
from .analysts.prediction_market_analyst import create_prediction_market_analyst
from .analysts.chart_vision_analyst import create_chart_vision_analyst
from .analysts.ict_analyst import create_ict_analyst

from .researchers.bear_researcher import create_bear_researcher
from .researchers.bull_researcher import create_bull_researcher

from .risk_mgmt.aggressive_debator import create_aggressive_debator
from .risk_mgmt.conservative_debator import create_conservative_debator
from .risk_mgmt.neutral_debator import create_neutral_debator

from .managers.research_manager import create_research_manager
from .managers.risk_manager import create_risk_manager

from .trader.trader import create_trader
from .trader.execution_optimizer import create_execution_optimizer

__all__ = [
    "FinancialSituationMemory",
    "AgentState",
    "create_msg_delete",
    "InvestDebateState",
    "RiskDebateState",
    "create_bear_researcher",
    "create_bull_researcher",
    "create_research_manager",
    "create_fundamentals_analyst",
    "create_market_analyst",
    "create_neutral_debator",
    "create_news_analyst",
    "create_aggressive_debator",
    "create_risk_manager",
    "create_conservative_debator",
    "create_social_media_analyst",
    "create_trader",
    # Phase 9: Advanced agents
    "create_quant_analyst",
    "create_onchain_analyst",
    "create_macro_geo_analyst",
    "create_correlation_analyst",
    "create_execution_optimizer",
    # Phase 14: Prediction market agent
    "create_prediction_market_analyst",
    # TradingView Vision & Smart Money Concepts Agents
    "create_chart_vision_analyst",
    "create_ict_analyst",
]
