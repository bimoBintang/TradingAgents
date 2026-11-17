"""Smoke test the three tiers against a running Ollama.

    PYTHONPATH=<repo root>:<repo root>/TradingAgents python deploy/ollama/smoke_test.py
"""
from tradingagents.llm_clients.factory import create_llm_client
from langchain_core.tools import tool

TIERS = {"deep": "deepseek-r1:32b", "smart": "qwen2.5:7b", "fast": "qwen2.5:7b"}


@tool
def get_price(ticker: str) -> float:
    """Return the latest price for a ticker."""
    return 1.1


def main() -> int:
    bad = 0
    for tier, model in TIERS.items():
        llm = create_llm_client("ollama", model, timeout=900).get_llm()
        out = llm.invoke("Reply with exactly: OK").content
        print(f"[{tier}] {model}: {out!r}")
        if "<think>" in out:
            print("  FAIL: <think> leaked into the answer"); bad += 1
        if tier != "deep":  # r1 cannot call tools in Ollama; only smart/fast bind tools in this app
            msg = llm.bind_tools([get_price]).invoke("What is the price of EURUSD? Use the tool.")
            ok = bool(msg.tool_calls)
            print(f"  tool call: {'ok' if ok else 'FAIL (no tool_calls)'}")
            bad += 0 if ok else 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
