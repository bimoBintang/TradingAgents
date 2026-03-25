"""
Example: Basic 3-agent Pipeline using the CMAOP platform.

Run this file directly to see the orchestrator in action:
    python -m orchestrator.example
"""

import asyncio
import logging

from orchestrator.orchestrator import Orchestrator
from orchestrator.core import Topology

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")


async def main():
    # ── Build the orchestrator ─────────────────────────────────────────────
    orch = Orchestrator(ticker="BTCUSDT", topology=Topology.PIPELINE)

    # ── Register Tools ─────────────────────────────────────────────────────
    @orch.tool(name="get_price", category="market")
    def get_price(ticker: str) -> float:
        """Return a mock price for demonstration."""
        return 65_432.10

    # ── Register Agents ────────────────────────────────────────────────────

    @orch.agent(role="Market Analyst", agent_id="market_analyst", priority=10)
    async def market_analyst_agent(state, bus, tools, **kwargs):
        resolved = tools.get_for_agent(categories=["market"])
        price = resolved["get_price"](ticker=state.ticker)
        report = {"price": price, "signal": "BULLISH", "confidence": 0.78}
        state.set("analysis", "market_report", report, writer="market_analyst")
        print(f"[MarketAnalyst] Price: ${price:,.2f} → Signal: BULLISH")
        return report

    @orch.agent(
        role="Risk Manager",
        agent_id="risk_manager",
        depends_on=["market_analyst"],
        priority=20,
    )
    async def risk_manager_agent(state, bus, tools, **kwargs):
        market = state.get("analysis", "market_report", {})
        confidence = market.get("confidence", 0.5)
        risk_score = 1.0 - confidence
        approved = risk_score < 0.35
        report = {
            "risk_score": risk_score,
            "approved": approved,
            "max_allocation_pct": 0.10 if approved else 0.0,
        }
        state.set("risk", "risk_report", report, writer="risk_manager")
        print(f"[RiskManager] Risk: {risk_score:.2f} → {'✅ Approved' if approved else '❌ Rejected'}")
        return report

    @orch.agent(
        role="Trader Agent",
        agent_id="trader",
        depends_on=["risk_manager"],
        priority=30,
    )
    async def trader_agent(state, bus, tools, **kwargs):
        risk = state.get("risk", "risk_report", {})
        market = state.get("analysis", "market_report", {})
        if not risk.get("approved", False):
            decision = {"action": "HOLD", "reason": "Risk not approved", "confidence": 0.0}
        else:
            decision = {
                "action": "BUY",
                "ticker": state.ticker,
                "quantity_pct": risk.get("max_allocation_pct", 0.05),
                "confidence": market.get("confidence", 0.5),
                "reason": "Bullish signal approved by risk manager",
            }
        state.add_decision(decision)
        print(f"[Trader] Decision: {decision['action']} {state.ticker} "
              f"(confidence: {decision['confidence']:.0%})")
        return decision

    # ── Run ────────────────────────────────────────────────────────────────
    print("\n" + "="*55)
    print("  CMAOP — Custom Multi-Agent Orchestration Platform")
    print("  Running Pipeline Example — ticker: BTCUSDT")
    print("="*55 + "\n")

    result = await orch.run()

    print("\n" + "-"*55)
    print("  RESULT SUMMARY")
    print("-"*55)
    for k, v in result.summary().items():
        print(f"  {k:<25} {v}")
    print("="*55 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
