"""Deterministic baseline strategies, and a head-to-head comparison harness.

WHY THIS EXISTS
---------------
A multi-agent LLM stack is expensive (one full pipeline per decision) and
non-deterministic. Neither of those is a problem if it beats the dumb
alternatives — and neither is justified if it doesn't. Until the agent
stack is measured against a baseline ON THE SAME SIMULATOR, no other
optimization can be prioritized honestly: a Sharpe of 1.4 means nothing
without knowing that always-long scored 1.9 over the same bars.

These baselines are free and instant (no LLM calls), so they can be run
over any period, repeatedly, at zero cost. They plug into BacktestRunner
through its `decision_fn` hook, so they go through the exact same exit
simulation, cost model, and metrics as the agents do — the comparison is
apples-to-apples by construction.

Usage:
    from tradingagents.backtesting.baselines import compare_against_baselines

    results = compare_against_baselines("NVDA", "2026-01-05", "2026-06-28")
    print(results["report"])
"""

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Baseline decision functions ───────────────────────────────────────
# Signature matches BacktestRunner's decision_fn: (ticker, bars, idx) -> payload.
# They return the same dict shape a TradeDecision serializes to, so
# _extract_decision() handles them without a special case.


def buy_and_hold_decision(ticker: str, bars: List[Any], idx: int) -> Dict[str, Any]:
    """Always-long benchmark: full size, no stop, no target, longest horizon.

    With BacktestRunner's non-overlapping rule this produces back-to-back
    long positions — i.e. continuous long exposure, which is the honest
    "did you beat just owning it?" benchmark. (It is deliberately NOT a
    single 1-trade hold: one trade yields no distribution to compute
    Sharpe or drawdown from.)
    """
    return {
        "action": "BUY",
        "confidence_score": 1.0,
        "quantity_pct": 1.0,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "time_horizon": "long_term",
    }


def make_sma_crossover_decision(
    fast: int = 20,
    slow: int = 50,
    allow_short: bool = False,
    quantity_pct: float = 1.0,
) -> Callable[[str, List[Any], int], Dict[str, Any]]:
    """Classic moving-average crossover — the standard 'is your fancy system
    better than three lines of arithmetic?' benchmark.

    Long when fast SMA > slow SMA. Flat otherwise (or short, if
    `allow_short`). No stop/target: this measures the SIGNAL, so that any
    edge the agent stack shows can be attributed to its signal rather than
    to a luckier exit rule.

    Uses only bars strictly BEFORE the decision bar's close... it includes
    the decision bar's own close, which is correct: the entry also happens
    at that close, so no future information is used.
    """
    def decide(ticker: str, bars: List[Any], idx: int) -> Dict[str, Any]:
        if idx + 1 < slow:
            return {"action": "HOLD", "confidence_score": 0.0}

        closes = [b.close for b in bars[idx + 1 - slow: idx + 1]]
        slow_ma = sum(closes) / slow
        fast_ma = sum(closes[-fast:]) / fast

        if fast_ma > slow_ma:
            action = "BUY"
        elif allow_short:
            action = "SELL"
        else:
            return {"action": "HOLD", "confidence_score": 0.0}

        return {
            "action": action,
            "confidence_score": 1.0,
            "quantity_pct": quantity_pct,
            "stop_loss_pct": None,
            "take_profit_pct": None,
            "time_horizon": "short_term",
        }

    return decide


# ── Comparison harness ────────────────────────────────────────────────

def compare_against_baselines(
    ticker: str,
    start_date: str,
    end_date: str,
    config: Optional[Dict[str, Any]] = None,
    include_agents: bool = False,
    selected_analysts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the baselines (and optionally the agent stack) over the same
    bars, same costs, same exit simulator — then tabulate them side by side.

    Args:
        ticker: Symbol to test.
        start_date / end_date: YYYY-MM-DD range.
        config: TradingAgents config (supplies the cost model; the same
            commission/slippage applies to every strategy so no one gets a
            cheaper simulation than another).
        include_agents: Run the full LLM pipeline too. OFF by default
            because it costs one full agent cycle per entry — opt in
            deliberately, and expect it to dominate the runtime and bill.
        selected_analysts: Analyst list for the agent run.

    Returns:
        {"metrics": {name: BacktestMetrics}, "report": str}
    """
    from .backtest_runner import BacktestRunner

    strategies: Dict[str, Optional[Callable]] = {
        "Always-Long (buy & hold)": buy_and_hold_decision,
        "SMA 20/50 crossover": make_sma_crossover_decision(20, 50),
    }
    if include_agents:
        strategies["LLM Agent Stack"] = None   # None => use the graph

    results: Dict[str, Any] = {}
    for name, fn in strategies.items():
        logger.info("Running baseline comparison: %s", name)
        runner = BacktestRunner(
            config=config,
            selected_analysts=selected_analysts,
            decision_fn=fn,
        )
        try:
            results[name] = runner.run(ticker, start_date, end_date)
        except Exception as e:
            logger.error("Strategy %r failed: %s", name, e, exc_info=True)
            results[name] = None

    return {"metrics": results, "report": format_comparison(results, ticker, start_date, end_date)}


def format_comparison(
    results: Dict[str, Any],
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Render a side-by-side markdown table of strategy metrics."""
    lines = [
        f"# Strategy Comparison — {ticker}",
        f"**Period**: {start_date} → {end_date}",
        "",
        "All strategies ran through the identical exit simulator, cost model,",
        "and metrics — differences are strategy, not methodology.",
        "",
        "| Strategy | Trades | Return | Sharpe | MaxDD | Win Rate | Dir. Acc | Avg Hold |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for name, m in results.items():
        if m is None:
            lines.append(f"| {name} | — | FAILED | — | — | — | — | — |")
            continue
        actionable = m.buy_count + m.sell_count
        pf_sharpe = f"{m.sharpe_ratio:.2f}"
        lines.append(
            f"| {name} | {actionable} | {m.total_return_pct:+.2f}% | {pf_sharpe} "
            f"| {m.max_drawdown_pct:.2f}% | {m.win_rate:.1f}% "
            f"| {m.directional_accuracy:.1f}% | {m.avg_holding_days:.1f}d |"
        )

    lines.append("")

    # The verdict is the whole point of this module — state it plainly
    # rather than leaving the reader to eyeball the table.
    valid = {k: v for k, v in results.items() if v is not None}
    agent_key = next((k for k in valid if "Agent" in k), None)
    if agent_key and len(valid) > 1:
        agent = valid[agent_key]
        rivals = {k: v for k, v in valid.items() if k != agent_key}
        best_rival = max(rivals.items(), key=lambda kv: kv[1].sharpe_ratio)
        lines.append("## Verdict")
        if agent.sharpe_ratio > best_rival[1].sharpe_ratio:
            lines.append(
                f"Agent stack Sharpe **{agent.sharpe_ratio:.2f}** beats the best baseline "
                f"({best_rival[0]}, {best_rival[1].sharpe_ratio:.2f}). The added cost and "
                "non-determinism bought something — verify it holds on another period before trusting it."
            )
        else:
            lines.append(
                f"Agent stack Sharpe **{agent.sharpe_ratio:.2f}** does NOT beat "
                f"{best_rival[0]} ({best_rival[1].sharpe_ratio:.2f}). On this period the LLM pipeline "
                "is not paying for itself — fix that before adding new strategies on top of it."
            )
    else:
        lines.append(
            "_Run with `include_agents=True` to put the LLM stack on this table — "
            "baselines alone only tell you what the bar is._"
        )

    return "\n".join(lines)
