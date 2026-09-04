"""Forward measurement: does the agent stack beat the dumb baselines?

THE PROBLEM THIS SOLVES
-----------------------
`tradingagents/backtesting/baselines.py` can compare strategies on
historical bars, and that is valid for deterministic rules. It is NOT
valid for the LLM agent stack: the model's pretraining already covers the
historical window, so a "prediction" about 2024 by a model trained through
2025 is contaminated by lookahead that no amount of careful backtesting
can remove. Any historical agent-vs-baseline number is unfalsifiable.

The only sound method is to measure forward. At the moment the agent
decides — before the outcome exists for anyone — record:

  - what the agent chose
  - what each baseline would have chosen, at the SAME instant, from the
    SAME price history, at the SAME entry price, with the SAME horizon

then resolve all of them later against real prices. No strategy can see
the future, so the comparison is honest by construction.

This is deliberately independent of whether trades were actually executed:
it measures DECISION QUALITY, so it works in paper mode, in live mode,
and even with execution disabled.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from api.models import BenchmarkDecision

logger = logging.getLogger("api.services.forward_benchmark")

# All strategies share one horizon so the comparison is apples-to-apples.
DEFAULT_HORIZON_DAYS = 5

# Round-trip cost charged to every non-HOLD decision, in percent. Baselines
# pay it too — a strategy that trades more should be penalized more, which
# is precisely the comparison a cost-free benchmark would hide.
DEFAULT_COST_PCT = 0.30

AGENT_STRATEGY = "agent"


# ── Price access ──────────────────────────────────────────────────────

def _recent_closes(ticker: str, bars: int = 60) -> List[float]:
    """Closing prices up to and including now — never beyond.

    Baselines are computed from exactly this window, so they see no more
    information than the agent did at the same instant.
    """
    try:
        import yfinance as yf
        period = "6mo" if bars > 60 else "3mo"
        data = yf.Ticker(ticker).history(period=period)
        if data.empty:
            return []
        return [float(c) for c in data["Close"].tolist()][-bars:]
    except Exception as e:
        logger.warning("Price history fetch failed for %s: %s", ticker, e)
        return []


def _current_price(ticker: str) -> Optional[float]:
    closes = _recent_closes(ticker, bars=2)
    return closes[-1] if closes else None


# ── Baseline decisions, evaluated at decision time ────────────────────

def _baseline_actions(closes: List[float]) -> Dict[str, str]:
    """What each baseline would call, given only the history available now.

    Mirrors tradingagents/backtesting/baselines.py so the forward and
    historical harnesses can never quietly disagree about what "SMA 20/50"
    or "buy and hold" means.
    """
    actions = {"buy_and_hold": "BUY"}

    fast, slow = 20, 50
    if len(closes) >= slow:
        window = closes[-slow:]
        slow_ma = sum(window) / slow
        fast_ma = sum(window[-fast:]) / fast
        actions["sma_20_50"] = "BUY" if fast_ma > slow_ma else "HOLD"
    else:
        actions["sma_20_50"] = "HOLD"

    return actions


# ── Recording ─────────────────────────────────────────────────────────

def record_decision_set(
    db: Session,
    user_id: int,
    ticker: str,
    agent_action: str,
    agent_confidence: Optional[float] = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> int:
    """Record the agent's call plus every baseline's call for this instant.

    Returns the number of rows written (0 if the price was unavailable —
    a missing price must not produce a half-recorded comparison where the
    agent is scored and the baselines are not).
    """
    closes = _recent_closes(ticker)
    if not closes:
        logger.warning("No price for %s — skipping benchmark record.", ticker)
        return 0

    entry_price = closes[-1]
    now = datetime.now(timezone.utc)

    normalized = (agent_action or "HOLD").upper()
    if normalized in ("STRONG_BUY",):
        normalized = "BUY"
    elif normalized in ("STRONG_SELL",):
        normalized = "SELL"

    rows: Dict[str, Dict[str, Any]] = {
        AGENT_STRATEGY: {"action": normalized, "confidence": agent_confidence},
    }
    for name, action in _baseline_actions(closes).items():
        rows[name] = {"action": action, "confidence": None}

    for strategy, spec in rows.items():
        db.add(BenchmarkDecision(
            user_id=user_id,
            strategy=strategy,
            ticker=ticker,
            action=spec["action"],
            confidence=spec["confidence"],
            decided_at=now,
            entry_price=entry_price,
            horizon_days=horizon_days,
        ))

    db.commit()
    logger.info(
        "Benchmark recorded for user %d on %s @ %.4f: agent=%s, baselines=%s",
        user_id, ticker, entry_price, normalized,
        {k: v["action"] for k, v in rows.items() if k != AGENT_STRATEGY},
    )
    return len(rows)


# ── Resolution ────────────────────────────────────────────────────────

def resolve_due(db: Session, cost_pct: float = DEFAULT_COST_PCT) -> int:
    """Mark to market every decision whose horizon has elapsed.

    Safe to call on a timer; already-resolved rows are skipped. Returns the
    number newly resolved.
    """
    now = datetime.now(timezone.utc)
    pending = db.query(BenchmarkDecision).filter(
        BenchmarkDecision.resolved == False  # noqa: E712 - SQL, not Python truthiness
    ).all()

    price_cache: Dict[str, Optional[float]] = {}
    resolved_count = 0

    for row in pending:
        decided = row.decided_at
        if decided is None:
            continue
        if decided.tzinfo is None:
            decided = decided.replace(tzinfo=timezone.utc)
        if now < decided + timedelta(days=row.horizon_days):
            continue

        if row.ticker not in price_cache:
            price_cache[row.ticker] = _current_price(row.ticker)
        exit_price = price_cache[row.ticker]
        if exit_price is None:
            continue

        raw_pct = ((exit_price - row.entry_price) / row.entry_price) * 100.0
        if row.action == "BUY":
            net = raw_pct - cost_pct
        elif row.action == "SELL":
            net = -raw_pct - cost_pct
        else:
            net = 0.0   # HOLD takes no position and pays no cost

        row.exit_price = exit_price
        row.return_pct = net
        row.resolved = True
        row.resolved_at = now
        resolved_count += 1

    if resolved_count:
        db.commit()
        logger.info("Resolved %d benchmark decisions.", resolved_count)
    return resolved_count


# ── Comparison ────────────────────────────────────────────────────────

def build_comparison(db: Session, user_id: int, ticker: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate resolved decisions per strategy into a comparison.

    Returns a dict with per-strategy stats and a plain-language verdict.
    """
    query = db.query(BenchmarkDecision).filter(
        BenchmarkDecision.user_id == user_id,
        BenchmarkDecision.resolved == True,  # noqa: E712
    )
    if ticker:
        query = query.filter(BenchmarkDecision.ticker == ticker)
    rows = query.all()

    by_strategy: Dict[str, List[BenchmarkDecision]] = {}
    for r in rows:
        by_strategy.setdefault(r.strategy, []).append(r)

    stats: Dict[str, Dict[str, Any]] = {}
    for strategy, items in by_strategy.items():
        acted = [i for i in items if i.action in ("BUY", "SELL")]
        returns = [i.return_pct or 0.0 for i in acted]

        equity = 100.0
        peak = 100.0
        max_dd = 0.0
        for r in returns:
            equity *= 1 + r / 100.0
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)

        wins = [r for r in returns if r > 0]
        stats[strategy] = {
            "decisions": len(items),
            "positions_taken": len(acted),
            "total_return_pct": equity - 100.0,
            "avg_return_pct": (sum(returns) / len(returns)) if returns else 0.0,
            "win_rate_pct": (len(wins) / len(returns) * 100.0) if returns else 0.0,
            "max_drawdown_pct": max_dd,
        }

    pending = db.query(BenchmarkDecision).filter(
        BenchmarkDecision.user_id == user_id,
        BenchmarkDecision.resolved == False,  # noqa: E712
    ).count()

    return {
        "strategies": stats,
        "pending_resolution": pending,
        "verdict": _verdict(stats),
    }


def _verdict(stats: Dict[str, Dict[str, Any]]) -> str:
    """State the conclusion outright — a table nobody interprets is a table
    that changes no decision."""
    agent = stats.get(AGENT_STRATEGY)
    rivals = {k: v for k, v in stats.items() if k != AGENT_STRATEGY}

    if not agent or not rivals:
        return "Not enough data yet — the agent and at least one baseline must have resolved decisions."

    # Sample-size gate. A handful of resolved decisions is noise, and
    # declaring a winner off it is exactly the error this harness exists
    # to prevent.
    if agent["positions_taken"] < 20:
        return (
            f"Too early to judge: the agent has only {agent['positions_taken']} resolved "
            "positions. Aim for at least 20-30 before reading anything into the numbers."
        )

    best_name, best = max(rivals.items(), key=lambda kv: kv[1]["total_return_pct"])
    if agent["total_return_pct"] > best["total_return_pct"]:
        return (
            f"Agent stack leads: {agent['total_return_pct']:+.2f}% vs {best_name} "
            f"{best['total_return_pct']:+.2f}%. Measured forward, so this is not lookahead — "
            "keep accumulating decisions before sizing up on it."
        )
    return (
        f"Agent stack trails {best_name}: {agent['total_return_pct']:+.2f}% vs "
        f"{best['total_return_pct']:+.2f}%. The LLM pipeline is not currently paying for its "
        "cost and non-determinism — fix that before building new strategies on top of it."
    )


def format_comparison_report(comparison: Dict[str, Any]) -> str:
    """Render the comparison as markdown."""
    lines = [
        "# Forward Benchmark — Agent vs Baselines",
        "",
        "Every strategy was recorded at the same instant, same entry price, same",
        "horizon, same costs — and none could see the outcome. Unlike a historical",
        "backtest of an LLM, this comparison is free of pretraining lookahead.",
        "",
        "| Strategy | Decisions | Positions | Total Return | Avg | Win Rate | MaxDD |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in sorted(comparison["strategies"].items()):
        lines.append(
            f"| {name} | {s['decisions']} | {s['positions_taken']} "
            f"| {s['total_return_pct']:+.2f}% | {s['avg_return_pct']:+.2f}% "
            f"| {s['win_rate_pct']:.1f}% | {s['max_drawdown_pct']:.2f}% |"
        )
    lines += [
        "",
        f"_Pending resolution: {comparison['pending_resolution']} decisions_",
        "",
        "## Verdict",
        "",
        comparison["verdict"],
    ]
    return "\n".join(lines)
