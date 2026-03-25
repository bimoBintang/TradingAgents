"""Tests for Phase 4 SDK & CLI components."""

import asyncio
import pytest

from orchestrator.sdk.agent_builder import (
    agent, tool, get_registered_agents, get_registered_tools,
    build_orchestrator, AgentDefinition, list_agents, list_tools,
    _REGISTERED_AGENTS, _REGISTERED_TOOLS,
)
from orchestrator.sdk.presets import create_trading_orchestrator
from orchestrator.cli.orchctl import build_parser, main


# ── Fixture: clear global registries between tests ───────────────────────────

@pytest.fixture(autouse=True)
def clear_registries():
    """Ensure each test starts with empty global registries."""
    _REGISTERED_AGENTS.clear()
    _REGISTERED_TOOLS.clear()
    yield
    _REGISTERED_AGENTS.clear()
    _REGISTERED_TOOLS.clear()


# ── SDK: @agent decorator ─────────────────────────────────────────────────────

class TestAgentDecorator:
    def test_decorator_registers_agent(self):
        @agent(role="Test Analyst", agent_id="test_analyst")
        async def test_analyst(state, bus, tools, **kwargs):
            return "ok"

        agents = get_registered_agents()
        assert "test_analyst" in agents

    def test_agent_def_attributes(self):
        @agent(role="Quant", agent_id="quant", priority=15, depends_on=["data_loader"])
        async def quant(state, bus, tools, **kwargs):
            return {}

        defn = get_registered_agents()["quant"]
        assert defn.role == "Quant"
        assert defn.priority == 15
        assert defn.depends_on == ["data_loader"]

    def test_agent_def_attached_to_fn(self):
        @agent(role="Risk", agent_id="risk_mgr")
        async def risk_mgr(state, bus, tools, **kwargs):
            return {}

        assert hasattr(risk_mgr, "__agent_def__")
        assert isinstance(risk_mgr.__agent_def__, AgentDefinition)

    def test_to_router_kwargs(self):
        @agent(role="Trader", agent_id="trader_bot", priority=30)
        async def trader_bot(state, bus, tools, **kwargs):
            return {}

        kwargs = trader_bot.__agent_def__.to_router_kwargs()
        assert kwargs["agent_id"] == "trader_bot"
        assert kwargs["role"] == "Trader"
        assert kwargs["priority"] == 30
        assert callable(kwargs["handler"])


# ── SDK: @tool decorator ──────────────────────────────────────────────────────

class TestToolDecorator:
    def test_decorator_registers_tool(self):
        @tool(name="fetch_price", category="market")
        def fetch_price(ticker: str) -> float:
            return 65000.0

        tools = get_registered_tools()
        assert "fetch_price" in tools

    def test_tool_callable_after_registration(self):
        @tool(name="multiply", category="math")
        def multiply(a, b):
            return a * b

        # Tool function is still directly callable
        assert multiply(3, 4) == 12

    def test_tool_def_to_registry_kwargs(self):
        @tool(name="mock_tool", category="test", requires_auth=True)
        def mock_tool():
            pass

        kwargs = get_registered_tools()["mock_tool"].to_registry_kwargs()
        assert kwargs["name"] == "mock_tool"
        assert kwargs["category"] == "test"
        assert kwargs["requires_auth"] is True

    def test_list_agents_and_tools(self):
        @agent(role="Analyst", agent_id="my_analyst")
        async def my_analyst(state, bus, tools, **kwargs):
            return {}

        @tool(name="my_tool", category="data")
        def my_tool():
            return 42

        assert len(list_agents()) == 1
        assert len(list_tools()) == 1


# ── SDK: build_orchestrator ───────────────────────────────────────────────────

class TestBuildOrchestrator:
    def test_builds_with_registered_agents(self):
        @agent(role="Analyst", agent_id="sdk_analyst", priority=10)
        async def sdk_analyst(state, bus, tools, **kwargs):
            return "analysis done"

        @tool(name="sdk_price", category="market")
        def sdk_price(ticker: str):
            return 65000

        orch = build_orchestrator("BTCUSDT", topology="pipeline")
        assert "sdk_analyst" in orch.router._agents
        assert orch.ticker == "BTCUSDT"

    def test_run_with_sdk_agents(self):
        @agent(role="Simple", agent_id="simple_agent", priority=5)
        async def simple_agent(state, bus, tools, **kwargs):
            state.add_decision({"action": "HOLD", "confidence": 0.5})
            return {"action": "HOLD"}

        orch = build_orchestrator("ETHUSDT")
        result = asyncio.run(orch.run())
        assert result.success_rate == 1.0
        assert result.final_decision["action"] == "HOLD"


# ── SDK: Presets ──────────────────────────────────────────────────────────────

class TestPresets:
    def test_create_trading_orchestrator(self):
        orch = create_trading_orchestrator(
            ticker="BTCUSDT",
            topology="pipeline",
            budget_usd=0.50,
        )
        assert orch.ticker == "BTCUSDT"
        assert hasattr(orch, "guard")
        assert hasattr(orch, "meter")
        assert hasattr(orch, "breaker")
        assert hasattr(orch, "ltm")
        assert hasattr(orch, "rb")

    def test_preset_allowed_tickers(self):
        orch = create_trading_orchestrator(
            ticker="BTCUSDT",
            allowed_tickers={"BTCUSDT", "ETHUSDT"},
        )
        assert "BTCUSDT" in orch.guard.allowed_tickers
        assert "ETHUSDT" in orch.guard.allowed_tickers


# ── CLI: Parser & Commands ────────────────────────────────────────────────────

class TestCLI:
    def test_parser_run_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.ticker == "BTCUSDT"
        assert args.topology == "pipeline"
        assert args.budget == 1.00

    def test_parser_run_custom(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--ticker", "ETHUSDT", "--topology", "mesh", "--budget", "2.5"])
        assert args.ticker == "ETHUSDT"
        assert args.topology == "mesh"
        assert args.budget == 2.5

    def test_parser_memory_search(self):
        parser = build_parser()
        args = parser.parse_args(["memory", "search", "bitcoin bullish", "--top-k", "5"])
        assert args.query == "bitcoin bullish"
        assert args.top_k == 5

    def test_parser_token_usage_demo(self):
        parser = build_parser()
        args = parser.parse_args(["token-usage", "--demo"])
        assert args.demo is True

    def test_cli_status_runs(self, capsys):
        main(["status"])
        captured = capsys.readouterr()
        assert "CMAOP Platform Status" in captured.out

    def test_cli_agents_empty(self, capsys):
        main(["agents"])
        captured = capsys.readouterr()
        assert "Registered Agents" in captured.out

    def test_cli_tools_empty(self, capsys):
        main(["tools"])
        captured = capsys.readouterr()
        assert "Registered Tools" in captured.out

    def test_cli_token_usage_demo(self, capsys):
        main(["token-usage", "--demo"])
        captured = capsys.readouterr()
        assert "Token Usage" in captured.out

    def test_cli_memory_stats(self, capsys):
        main(["memory", "stats"])
        captured = capsys.readouterr()
        assert "Memory Statistics" in captured.out
