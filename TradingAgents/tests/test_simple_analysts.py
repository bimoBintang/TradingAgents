"""ICT / ChartVision as plain graph nodes, and their reports reaching the synthesizer."""
import pytest

pytest.importorskip("orchestrator")


def test_ict_node_real_vs_unavailable(monkeypatch):
    from tradingagents.agents.analysts import ict_analyst as m
    real = {"data_quality": "REAL_OHLC", "ict_bias": "BULLISH", "current_price": 100.0,
            "ote_zone": {"fib_618": 1, "fib_786": 0, "in_ote_zone": True}}

    async def ok(**kw): return real
    monkeypatch.setattr(m, "ict_agent_handler", ok)
    out = m.create_ict_analyst()({"company_of_interest": "BTCUSDT"})
    assert set(out) == {"ict_report"} and "BULLISH" in out["ict_report"]

    async def fake(**kw): return {**real, "data_quality": "SIMULATED_NO_DATA"}
    monkeypatch.setattr(m, "ict_agent_handler", fake)
    assert "unavailable" in m.create_ict_analyst()({"company_of_interest": "EURUSD"})["ict_report"]

    async def boom(**kw): raise RuntimeError("net down")
    monkeypatch.setattr(m, "ict_agent_handler", boom)
    assert "unavailable" in m.create_ict_analyst()({"company_of_interest": "X"})["ict_report"]


def test_chart_vision_node_formats_quant_report(monkeypatch):
    from tradingagents.agents.analysts import chart_vision_analyst as m

    async def fake(*a, **kw):
        return {"mode": "FALLBACK_QUANTITATIVE_TA", "primary_trend": "BULLISH", "chart_pattern": None,
                "key_support": None, "key_resistance": None, "visual_confidence": None,
                "recommendation": "BUY", "rationale": "indicators only"}
    monkeypatch.setattr(m, "chart_vision_agent_handler", fake)
    out = m.create_chart_vision_analyst()({"company_of_interest": "BTCUSDT"})
    assert set(out) == {"chart_vision_report"}
    t = out["chart_vision_report"]
    assert "BULLISH" in t and "n/a / n/a" in t and "None" not in t


def test_synthesizer_includes_new_reports():
    from tradingagents.agents.synthesizer import create_analyst_synthesizer
    seen = {}

    class LLM:
        def invoke(self, msgs):
            seen["t"] = " ".join(str(m.content) for m in msgs)
            return type("R", (), {"content": "ok"})()
    create_analyst_synthesizer(LLM())({"market_report": "m", "ict_report": "ICT-X",
                                       "chart_vision_report": "CV-Y", "trade_date": "2026-01-01",
                                       "company_of_interest": "BTC"})
    assert "ICT-X" in seen["t"] and "CV-Y" in seen["t"]
