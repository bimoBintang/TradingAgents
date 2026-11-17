"""Local Ollama setup: <think> stripping, base_url, tool-capable tier guard, debate tier, preset."""

import importlib
from types import SimpleNamespace as NS

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.openai_client import ThinkStrippingChatOpenAI, strip_think

DECISION = '<TRADE_DECISION>{"action": "BUY", "ticker": "EURUSD", "confidence_score": 0.8}</TRADE_DECISION>'


def test_strip_think_variants():
    assert strip_think("<think>hmm</think>answer") == "answer"
    assert strip_think("<think>a</think>x<think>b</think>y") == "xy"
    assert strip_think("<think>cut off, never closed") == ""
    assert strip_think("no tags") == "no tags"


def test_trade_decision_survives_and_parses():
    from tradingagents.execution.execution_engine import ExecutionEngine

    raw = f"<think>maybe {{\"action\": \"SELL\"}}</think>Plan.\n{DECISION}"
    cleaned = strip_think(raw)
    assert "SELL" not in cleaned
    eng = ExecutionEngine.__new__(ExecutionEngine)
    d = eng._parse_decision(cleaned)
    assert d is not None and d.action.value == "BUY"


def test_chat_result_is_stripped_and_raw_kept():
    llm = ThinkStrippingChatOpenAI(model="deepseek-r1:32b", api_key="x", base_url="http://localhost:1/v1")
    msg = AIMessage(content=f"<think>secret</think>{DECISION}")
    base = ChatResult(generations=[ChatGeneration(message=msg)])
    # Exercise only the post-processing by feeding the parent's result through it.
    import langchain_openai.chat_models.base as base_mod
    orig = base_mod.BaseChatOpenAI._create_chat_result
    base_mod.BaseChatOpenAI._create_chat_result = lambda self, r, g=None: base
    try:
        out = llm._create_chat_result({})
    finally:
        base_mod.BaseChatOpenAI._create_chat_result = orig
    m = out.generations[0].message
    assert m.content == DECISION and "secret" in m.additional_kwargs["reasoning"]


def test_ollama_uses_env_base_url_not_shared_backend_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434/v1")
    llm = create_llm_client("ollama", "qwen2.5:7b", base_url="https://api.anthropic.com").get_llm()
    assert isinstance(llm, ThinkStrippingChatOpenAI)
    assert "gpu-box" in str(llm.openai_api_base)
    monkeypatch.delenv("OLLAMA_BASE_URL")
    llm = create_llm_client("ollama", "qwen2.5:7b", base_url="https://api.anthropic.com").get_llm()
    assert "localhost:11434" in str(llm.openai_api_base)


def test_r1_gets_recommended_temperature():
    assert create_llm_client("ollama", "deepseek-r1:32b").get_llm().temperature == 0.6


def _guard(cfg):
    pytest.importorskip("orchestrator", reason="run with PYTHONPATH=<repo root>")
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    TradingAgentsGraph._check_tool_capable_tiers(NS(config=cfg))


def test_r1_rejected_on_tool_tiers_allowed_on_deep():
    base = {"llm_provider": "ollama", "deep_think_llm": "deepseek-r1:32b",
            "smart_think_llm": "qwen3:8b", "fast_think_llm": "qwen2.5:7b"}
    _guard(base)
    for tier in ("smart", "fast"):
        with pytest.raises(ValueError, match="deepseek-r1"):
            _guard({**base, f"{tier}_think_llm": "deepseek-r1:32b"})
    _guard({"llm_provider": "anthropic", "smart_think_llm": "deepseek-r1:32b"})  # other providers untouched


@pytest.mark.parametrize("tier,expected", [("deep", "DEEP"), ("smart", "SMART"), ("anything", "SMART")])
def test_debate_llm_tier(tier, expected):
    pytest.importorskip("orchestrator", reason="run with PYTHONPATH=<repo root>")
    from tradingagents.graph.setup import GraphSetup
    gs = GraphSetup.__new__(GraphSetup)
    gs.deep_thinking_llm, gs.smart_thinking_llm, gs.debate_tier = "DEEP", "SMART", tier
    assert gs._debate_llm() == expected


def test_preset_applies_only_when_env_set(monkeypatch):
    import tradingagents.default_config as dc
    try:
        monkeypatch.delenv("TRADINGAGENTS_LLM_PRESET", raising=False)
        assert importlib.reload(dc).DEFAULT_CONFIG["deep_think_llm_provider"] == "anthropic"
        monkeypatch.setenv("TRADINGAGENTS_LLM_PRESET", "ollama")
        cfg = importlib.reload(dc).DEFAULT_CONFIG
        assert (cfg["deep_think_llm"], cfg["smart_think_llm"], cfg["fast_think_llm"]) == (
            "deepseek-r1:32b", "qwen2.5:7b", "qwen2.5:7b")
        assert cfg["debate_llm_tier"] == "deep"
        assert cfg["analyst_execution"] == "sequential"
        assert (cfg["vision_llm_provider"], cfg["vision_llm"]) == ("ollama", "qwen2.5vl:7b")
    finally:
        monkeypatch.delenv("TRADINGAGENTS_LLM_PRESET", raising=False)
        importlib.reload(dc)


def _vision_model(monkeypatch, **cfg):
    pytest.importorskip("orchestrator")
    from orchestrator.sdk import chart_vision_agent as cv
    from tradingagents import default_config, llm_clients
    monkeypatch.setattr(default_config, "DEFAULT_CONFIG", {**default_config.DEFAULT_CONFIG, **cfg})
    seen = {}

    def fake(provider, model, **kw):
        seen["m"] = (provider, model)
        raise RuntimeError("stop")  # _run_vision_llm swallows it and returns None
    monkeypatch.setattr(llm_clients, "create_llm_client", fake)
    assert cv._run_vision_llm("aGk=", "BTCUSDT", "1h") is None
    return seen["m"]


def test_vision_uses_vision_llm_when_set(monkeypatch):
    got = _vision_model(monkeypatch, vision_llm_provider="ollama", vision_llm="qwen2.5vl:7b")
    assert got == ("ollama", "qwen2.5vl:7b")


def test_vision_falls_back_to_smart_tier(monkeypatch):
    got = _vision_model(monkeypatch, vision_llm_provider=None, vision_llm=None,
                        smart_think_llm_provider="anthropic", smart_think_llm="claude-sonnet-4-6")
    assert got == ("anthropic", "claude-sonnet-4-6")


def _edges(mode):
    pytest.importorskip("orchestrator")
    from unittest.mock import MagicMock
    from tradingagents.graph import setup as S
    seen = []

    class WF:
        def __init__(self, *a, **k): pass
        def add_node(self, *a, **k): pass
        def add_edge(self, s, d): seen.append((s, d))
        def add_conditional_edges(self, *a, **k): pass
        def compile(self): return None
    gs = S.GraphSetup(*([MagicMock()] * 3), {"market": 1, "news": 1}, *([MagicMock()] * 6),
                      analyst_execution=mode)
    gs.ANALYST_FACTORIES = {"market": lambda llm: None, "news": lambda llm: None}
    gs.SIMPLE_ANALYSTS = {"ict": lambda llm: None}
    orig = (S.StateGraph, S._build_analyst_subgraph)
    S.StateGraph, S._build_analyst_subgraph = WF, lambda *a, **k: None
    try:
        gs.setup_graph(["market", "news", "ict"])
    finally:
        S.StateGraph, S._build_analyst_subgraph = orig
    return seen


def test_analysts_parallel_vs_sequential_edges():
    par, seq = _edges("parallel"), _edges("sequential")
    S = "__start__"
    assert (S, "Market Analyst") in par and (S, "News Analyst") in par and (S, "Ict Analyst") in par
    assert (S, "Market Analyst") in seq and (S, "News Analyst") not in seq
    assert ("Market Analyst", "News Analyst") in seq
    assert ("News Analyst", "Ict Analyst") in seq and ("Ict Analyst", "Analyst Synthesizer") in seq
    assert ("Market Analyst", "Analyst Synthesizer") not in seq
