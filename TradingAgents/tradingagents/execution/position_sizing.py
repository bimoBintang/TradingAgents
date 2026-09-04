"""Position sizing — fractional Kelly and volatility targeting.

DESIGN NOTES (read before changing any of this)
-----------------------------------------------
Kelly is an AMPLIFIER. It scales your bet in proportion to the edge you
believe you have. Feed it an overestimated edge and it will confidently
size you into ruin — the failure mode is not "suboptimal growth", it's
"correctly executing a wrong belief with leverage". Three consequences,
all implemented below:

1. **Lower bound, not point estimate.** A 60% win rate measured over 20
   trades has a 95% lower confidence bound near 39% — i.e. you have not
   actually demonstrated an edge at all. We size off the Wilson score
   lower bound, so small samples automatically produce small bets and the
   size grows only as evidence accumulates. Using the raw sample win rate
   (the textbook formula) is the single most common way Kelly blows up in
   practice.

2. **Continuous form by default.** The familiar `W - (1-W)/R` is Kelly
   for a BINARY bet. A trade with a stop and a target is not binary: gaps,
   slippage and partial fills give a continuous outcome distribution. For
   that, Kelly is `f* = μ / σ²` (mean excess return over variance), which
   is what `kelly_fraction_continuous()` implements. The discrete version
   is kept for cross-checking, not as the primary path.

3. **Fractional, always.** Full Kelly is growth-optimal only if your
   probabilities are exact — they never are. Quarter-Kelly is the default
   here; half-Kelly captures ~75% of the growth at roughly half the
   drawdown and is the aggressive end of defensible.

Everything in this module is designed to only ever SHRINK a proposed
position, never expand one. That asymmetry is deliberate: a sizing bug
that makes positions too small costs return; one that makes them too
large costs the account.
"""

import math
from typing import List, Optional, Sequence

# Minimum completed trades before any edge estimate is trusted at all.
# Below this, the sizing functions return 0.0 (i.e. "no demonstrated
# edge" — fall back to the caller's own conservative default).
MIN_TRADES_FOR_EDGE = 30

# z-score for the Wilson lower bound (1.645 = 95% one-sided).
_Z_95_ONE_SIDED = 1.645


def wilson_lower_bound(wins: int, total: int, z: float = _Z_95_ONE_SIDED) -> float:
    """Conservative (lower-bound) estimate of a true win rate.

    The Wilson score interval behaves correctly at small n and near 0/1,
    where the normal approximation breaks down. Used instead of the raw
    `wins/total` so that Kelly cannot be fed an optimistic win rate that
    is really just sampling noise.
    """
    if total <= 0:
        return 0.0
    p_hat = wins / total
    denom = 1.0 + (z ** 2) / total
    center = (p_hat + (z ** 2) / (2 * total)) / denom
    margin = (
        z * math.sqrt(p_hat * (1 - p_hat) / total + (z ** 2) / (4 * total ** 2))
    ) / denom
    return max(0.0, center - margin)


def kelly_fraction_continuous(
    returns: Sequence[float],
    kelly_multiplier: float = 0.25,
    min_trades: int = MIN_TRADES_FOR_EDGE,
    max_fraction: float = 0.25,
) -> float:
    """Fractional Kelly for continuous outcomes: f* = μ / σ².

    Args:
        returns: Per-trade returns as decimal fractions (0.02 = +2%).
        kelly_multiplier: 0.25 = quarter-Kelly (default), 0.5 = half-Kelly.
        min_trades: Below this sample size, returns 0.0 — no demonstrated edge.
        max_fraction: Hard ceiling on the output, regardless of what the
            math says. σ² can be tiny in a quiet sample and send f* to
            absurd values; this is the backstop for that.

    Returns:
        Fraction of equity to allocate, in [0.0, max_fraction].
    """
    n = len(returns)
    if n < min_trades:
        return 0.0

    mean = sum(returns) / n
    if mean <= 0:
        return 0.0  # no positive expectancy → no bet

    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if variance <= 0:
        return 0.0  # zero variance in a real sample means the data is wrong

    # Shrink the mean toward zero by its own standard error. A mean that
    # isn't distinguishable from noise should not drive position size.
    std_err = math.sqrt(variance / n)
    mean_lower = max(0.0, mean - _Z_95_ONE_SIDED * std_err)
    if mean_lower <= 0:
        return 0.0

    full_kelly = mean_lower / variance
    return max(0.0, min(full_kelly * kelly_multiplier, max_fraction))


def kelly_fraction_discrete(
    wins: int,
    total: int,
    avg_win: float,
    avg_loss: float,
    kelly_multiplier: float = 0.25,
    min_trades: int = MIN_TRADES_FOR_EDGE,
    max_fraction: float = 0.25,
    use_lower_bound: bool = True,
) -> float:
    """Fractional Kelly for binary win/loss outcomes: f* = W - (1-W)/R.

    Kept mainly as a cross-check against `kelly_fraction_continuous()` —
    if the two disagree wildly, the return distribution is far from
    binary and the continuous form is the one to trust.

    Args:
        wins / total: Trade counts (NOT a pre-computed rate — the raw
            counts are needed for the confidence bound).
        avg_win / avg_loss: Average magnitudes, both POSITIVE.
        use_lower_bound: Size off the Wilson lower bound of the win rate
            rather than the raw sample rate. Leave on.
    """
    if total < min_trades or avg_loss <= 0 or avg_win <= 0:
        return 0.0

    win_rate = wilson_lower_bound(wins, total) if use_lower_bound else (wins / total)
    payoff_ratio = avg_win / avg_loss

    full_kelly = win_rate - (1 - win_rate) / payoff_ratio
    return max(0.0, min(full_kelly * kelly_multiplier, max_fraction))


def volatility_target_size(
    account_equity: float,
    daily_vol_target_pct: float,
    asset_daily_vol: float,
    price: float,
    min_vol: float = 0.002,
    max_position_pct: float = 0.25,
) -> float:
    """Size a position so its daily risk contribution hits a target.

    Args:
        account_equity: Total equity.
        daily_vol_target_pct: Risk budget per position as a decimal
            fraction of equity (0.001 = 0.1% daily vol contribution).
        asset_daily_vol: Realized daily volatility of the asset (stdev of
            daily returns, as a decimal fraction).
        price: Current price per unit.
        min_vol: FLOOR on the volatility input. Without it, a stale feed,
            an illiquid asset, or a low-activity window drives
            `asset_daily_vol` toward zero and the computed size toward
            infinity. A bare `if vol == 0` guard does not catch this —
            0.0001 is not zero but produces an equally catastrophic size.
            0.002 (0.2% daily ≈ 3% annualized) is below any real tradable
            asset, so it only ever binds on bad data.
        max_position_pct: Hard cap on notional as a fraction of equity.
            The final backstop: whatever the vol math produces, a single
            position never exceeds this.

    Returns:
        Number of units to trade (>= 0).
    """
    if account_equity <= 0 or price <= 0 or daily_vol_target_pct <= 0:
        return 0.0

    effective_vol = max(asset_daily_vol, min_vol)

    risk_budget = account_equity * daily_vol_target_pct
    dollar_vol_per_unit = price * effective_vol
    if dollar_vol_per_unit <= 0:
        return 0.0

    units = risk_budget / dollar_vol_per_unit

    # Cap by absolute notional exposure, not just by risk contribution.
    max_units = (account_equity * max_position_pct) / price
    return max(0.0, min(units, max_units))


def realized_volatility(prices: Sequence[float], lookback: int = 20) -> float:
    """Realized daily volatility (stdev of simple returns) over `lookback` bars.

    Returns 0.0 when there isn't enough data — callers must treat that as
    "unknown", not as "no risk"; `volatility_target_size()`'s `min_vol`
    floor is what turns it into a safe number.
    """
    if len(prices) < 2:
        return 0.0
    window = list(prices)[-(lookback + 1):]
    returns: List[float] = []
    for prev, cur in zip(window, window[1:]):
        if prev > 0:
            returns.append((cur - prev) / prev)
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(max(0.0, variance))
