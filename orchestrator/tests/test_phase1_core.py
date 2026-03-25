"""Tests for Phase 1 Core Engine components."""

import asyncio
import pytest

from orchestrator.core.agent_bus import AgentBus, Message
from orchestrator.core.state_manager import StateManager
from orchestrator.core.topology_router import TopologyRouter, Topology
from orchestrator.core.tool_registry import ToolRegistry
from orchestrator.orchestrator import Orchestrator


# ── AgentBus Tests ────────────────────────────────────────────────────────────

class TestAgentBus:
    def setup_method(self):
        self.bus = AgentBus(session_id="test-session")

    def test_register_agent(self):
        self.bus.register_agent("analyst_1", "Technical Analyst")
        assert "analyst_1" in self.bus.active_agents

    def test_subscribe_and_publish(self):
        received = []

        def handler(msg: Message):
            received.append(msg.payload)

        self.bus.subscribe("price.update", handler)
        asyncio.run(self.bus.publish(Message(
            topic="price.update",
            sender="market_feed",
            payload={"price": 65000}
        )))
        assert len(received) == 1
        assert received[0]["price"] == 65000

    def test_multiple_subscribers(self):
        count = []

        self.bus.subscribe("test.topic", lambda m: count.append(1))
        self.bus.subscribe("test.topic", lambda m: count.append(2))

        asyncio.run(self.bus.publish(Message(
            topic="test.topic", sender="test", payload={}
        )))
        assert len(count) == 2

    def test_message_log(self):
        asyncio.run(self.bus.publish(Message(
            topic="any.topic", sender="test", payload="hello"
        )))
        msgs = self.bus.get_messages()
        assert len(msgs) == 1
        assert msgs[0].payload == "hello"


# ── StateManager Tests ────────────────────────────────────────────────────────

class TestStateManager:
    def setup_method(self):
        self.state = StateManager(ticker="BTCUSDT", session_id="test-123")

    def test_set_and_get(self):
        self.state.set("analysis", "report", {"signal": "BUY"})
        assert self.state.get("analysis", "report") == {"signal": "BUY"}

    def test_default_value(self):
        result = self.state.get("analysis", "nonexistent", default="fallback")
        assert result == "fallback"

    def test_add_decision(self):
        self.state.add_decision({"action": "BUY", "confidence": 0.85})
        decisions = self.state.get_decisions()
        assert len(decisions) == 1
        assert decisions[0]["action"] == "BUY"

    def test_final_decision(self):
        self.state.add_decision({"action": "HOLD", "confidence": 0.3})
        self.state.add_decision({"action": "BUY", "confidence": 0.9})
        assert self.state.get_final_decision()["action"] == "BUY"

    def test_agent_output(self):
        self.state.record_agent_output("quant", {"score": 0.89})
        assert self.state.get_agent_output("quant") == {"score": 0.89}

    def test_snapshot(self):
        self.state.set("market", "price", 65000)
        snap = self.state.snapshot()
        assert snap.ticker == "BTCUSDT"
        assert snap.namespaces["market"]["price"] == 65000


# ── ToolRegistry Tests ────────────────────────────────────────────────────────

class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_register_and_call(self):
        self.registry.register("add", lambda a, b: a + b, category="math")
        tools = self.registry.get_for_agent(categories=["math"])
        assert "add" in tools
        assert tools["add"](a=2, b=3) == 5

    def test_decorator_registration(self):
        @self.registry.tool(name="multiply", category="math")
        def multiply(a, b):
            return a * b

        tools = self.registry.get_for_agent()
        assert multiply(a=3, b=4) == 12

    def test_call_tracking(self):
        self.registry.register("test_tool", lambda: 42)
        tools = self.registry.get_for_agent()
        tools["test_tool"]()
        tools["test_tool"]()
        assert self.registry.get_stats()["test_tool"] == 2


# ── Orchestrator Integration Test ─────────────────────────────────────────────

class TestOrchestrator:
    def test_pipeline_run(self):
        orch = Orchestrator(ticker="ETHUSDT", topology=Topology.PIPELINE)

        @orch.agent(role="Analyst", agent_id="analyst", priority=10)
        async def analyst(state, bus, tools, **kwargs):
            state.set("analysis", "signal", "BUY", writer="analyst")
            return {"signal": "BUY"}

        @orch.agent(role="Trader", agent_id="trader", depends_on=["analyst"], priority=20)
        async def trader(state, bus, tools, **kwargs):
            signal = state.get("analysis", "signal")
            decision = {"action": signal, "confidence": 0.80}
            state.add_decision(decision)
            return decision

        result = asyncio.run(orch.run())
        assert result.success_rate == 1.0
        assert result.final_decision["action"] == "BUY"

    def test_mesh_run(self):
        orch = Orchestrator(ticker="BTCUSDT", topology=Topology.MESH)

        @orch.agent(role="A", agent_id="a")
        async def agent_a(state, bus, tools, **kwargs):
            return "a_done"

        @orch.agent(role="B", agent_id="b")
        async def agent_b(state, bus, tools, **kwargs):
            return "b_done"

        result = asyncio.run(orch.run())
        assert result.success_rate == 1.0
        assert len(result.run_results) == 2
