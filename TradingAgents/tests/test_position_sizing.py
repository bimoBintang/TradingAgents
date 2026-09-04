"""Safety-property tests for position sizing.

These are not "does the math match a textbook" tests — they are guards on
the specific failure modes that make sizing code dangerous in production:
sizing off noise, sizing off a stale volatility feed, and Kelly silently
growing a position instead of capping it.
"""

import math
import random
from datetime import datetime

import pytest

from tradingagents.execution.position_sizing import (
    MIN_TRADES_FOR_EDGE,
    kelly_fraction_continuous,
    kelly_fraction_discrete,
    realized_volatility,
    volatility_target_size,
    wilson_lower_bound,
)


class TestWilsonLowerBound:
    """A win rate measured over few trades must not be trusted."""

    def test_small_sample_is_heavily_discounted(self):
        # 60% over 10 trades is not evidence of a 60% edge.
        assert wilson_lower_bound(6, 10) < 0.45

    def test_converges_toward_truth_with_more_data(self):
        bounds = [wilson_lower_bound(int(n * 0.6), n) for n in (10, 50, 200, 5000)]
        assert bounds == sorted(bounds), "bound must tighten upward as n grows"
        assert bounds[-1] == pytest.approx(0.6, abs=0.02)

    def test_never_exceeds_point_estimate(self):
        for n in (5, 25, 100, 1000):
            wins = int(n * 0.7)
            assert wilson_lower_bound(wins, n) <= wins / n

    def test_zero_total_is_safe(self):
        assert wilson_lower_bound(0, 0) == 0.0


class TestKellyContinuous:
    def test_below_min_trades_returns_zero(self):
        random.seed(0)
        few = [random.gauss(0.05, 0.02) for _ in range(MIN_TRADES_FOR_EDGE - 1)]
        # Even a gorgeous return series is not sized on if the sample is small.
        assert kelly_fraction_continuous(few) == 0.0

    def test_negative_expectancy_returns_zero(self):
        random.seed(1)
        losing = [random.gauss(-0.01, 0.03) for _ in range(200)]
        assert kelly_fraction_continuous(losing) == 0.0

    def test_positive_edge_produces_positive_fraction(self):
        random.seed(2)
        winning = [random.gauss(0.02, 0.03) for _ in range(200)]
        assert kelly_fraction_continuous(winning) > 0.0

    def test_respects_max_fraction_ceiling(self):
        # A tiny-variance, high-mean series sends raw Kelly enormous; the
        # ceiling is what stops that becoming a real position.
        returns = [0.05 + random.gauss(0, 0.0001) for _ in range(200)]
        assert kelly_fraction_continuous(returns, max_fraction=0.10) <= 0.10

    def test_multiplier_scales_down(self):
        # High-variance series, so raw Kelly (mu/sigma^2) lands well below
        # the ceiling and the multiplier is what actually decides the size.
        # A low-variance series pins BOTH multipliers to max_fraction —
        # correct behavior, but it tests the ceiling rather than the scaling.
        random.seed(3)
        winning = [random.gauss(0.05, 0.30) for _ in range(2000)]
        quarter = kelly_fraction_continuous(winning, kelly_multiplier=0.25, max_fraction=1.0)
        half = kelly_fraction_continuous(winning, kelly_multiplier=0.5, max_fraction=1.0)
        assert 0.0 < quarter < half < 1.0
        assert half == pytest.approx(quarter * 2, rel=1e-6)

    def test_noisy_mean_is_shrunk_to_zero(self):
        # Mean is positive but indistinguishable from zero given the spread —
        # must not produce a bet.
        random.seed(4)
        noisy = [random.gauss(0.001, 0.20) for _ in range(50)]
        assert kelly_fraction_continuous(noisy) == 0.0


class TestKellyDiscrete:
    def test_below_min_trades_returns_zero(self):
        assert kelly_fraction_discrete(15, 20, avg_win=0.05, avg_loss=0.02) == 0.0

    def test_lower_bound_is_more_conservative_than_raw(self):
        conservative = kelly_fraction_discrete(
            60, 100, avg_win=0.05, avg_loss=0.03, use_lower_bound=True, max_fraction=1.0
        )
        optimistic = kelly_fraction_discrete(
            60, 100, avg_win=0.05, avg_loss=0.03, use_lower_bound=False, max_fraction=1.0
        )
        assert conservative < optimistic

    def test_no_edge_returns_zero(self):
        # 50% win rate at 1:1 payoff has zero edge — Kelly must decline.
        assert kelly_fraction_discrete(50, 100, avg_win=0.03, avg_loss=0.03) == 0.0

    def test_zero_avg_loss_is_safe(self):
        # Guards against division by zero rather than returning infinity.
        assert kelly_fraction_discrete(60, 100, avg_win=0.05, avg_loss=0.0) == 0.0


class TestVolatilityTargetSize:
    """The failure mode this class exists for: near-zero volatility."""

    EQUITY = 100_000.0
    PRICE = 100.0
    TARGET = 0.001

    def test_normal_volatility_is_reasonable(self):
        units = volatility_target_size(self.EQUITY, self.TARGET, 0.02, self.PRICE)
        assert units == pytest.approx(50.0)

    def test_near_zero_volatility_does_not_explode(self):
        # Without a floor this is equity*target/(price*1e-5) = 100,000 units
        # = $10M of notional on a $100k account (100x leverage).
        units = volatility_target_size(self.EQUITY, self.TARGET, 0.00001, self.PRICE)
        notional = units * self.PRICE
        assert notional <= self.EQUITY * 0.25 + 1e-6

    def test_zero_volatility_does_not_return_infinity(self):
        units = volatility_target_size(self.EQUITY, self.TARGET, 0.0, self.PRICE)
        assert math.isfinite(units)
        assert units * self.PRICE <= self.EQUITY * 0.25 + 1e-6

    def test_max_position_pct_is_a_hard_cap(self):
        units = volatility_target_size(
            self.EQUITY, self.TARGET, 0.0001, self.PRICE, max_position_pct=0.05
        )
        assert units * self.PRICE <= self.EQUITY * 0.05 + 1e-6

    def test_invalid_inputs_return_zero(self):
        assert volatility_target_size(0, self.TARGET, 0.02, self.PRICE) == 0.0
        assert volatility_target_size(self.EQUITY, self.TARGET, 0.02, 0.0) == 0.0
        assert volatility_target_size(self.EQUITY, 0.0, 0.02, self.PRICE) == 0.0

    def test_higher_volatility_means_smaller_position(self):
        low = volatility_target_size(self.EQUITY, self.TARGET, 0.01, self.PRICE)
        high = volatility_target_size(self.EQUITY, self.TARGET, 0.05, self.PRICE)
        assert high < low


class TestRealizedVolatility:
    def test_insufficient_data_returns_zero(self):
        assert realized_volatility([100.0]) == 0.0
        assert realized_volatility([]) == 0.0

    def test_flat_prices_have_zero_volatility(self):
        assert realized_volatility([100.0] * 30) == pytest.approx(0.0)

    def test_detects_volatility(self):
        random.seed(5)
        prices = [100.0]
        for _ in range(60):
            prices.append(prices[-1] * (1 + random.gauss(0, 0.02)))
        assert realized_volatility(prices) > 0.005


class TestPortfolioManagerKellyIntegration:
    """Kelly must only ever shrink a position, and stay off until it has data."""

    def _pm(self, **kwargs):
        from tradingagents.execution.portfolio_manager import PortfolioManager
        return PortfolioManager(initial_cash=100_000, max_position_pct=0.10, **kwargs)

    def _add_trades(self, pm, n, mean=0.015, sd=0.04, seed=1):
        from tradingagents.execution.portfolio_manager import TradeRecord
        random.seed(seed)
        now = datetime.utcnow()
        for _ in range(n):
            r = random.gauss(mean, sd)
            pm.trade_history.append(
                TradeRecord("X", "BUY", 100.0, 100.0 * (1 + r), 10.0, now, now, 1000.0 * r)
            )

    def test_disabled_by_default(self):
        pm = self._pm()
        self._add_trades(pm, 200)
        assert pm.kelly_cap_pct() is None

    def test_returns_none_below_min_trades(self):
        pm = self._pm(kelly_enabled=True)
        self._add_trades(pm, MIN_TRADES_FOR_EDGE - 1)
        assert pm.kelly_cap_pct() is None, "must be None (no edge yet), not 0.0"

    def test_cap_never_exceeds_max_position_pct(self):
        pm = self._pm(kelly_enabled=True)
        self._add_trades(pm, 300, mean=0.05, sd=0.01)  # unrealistically good
        cap = pm.kelly_cap_pct()
        assert cap is not None
        assert cap <= pm.max_position_pct

    def test_losing_history_yields_no_cap(self):
        pm = self._pm(kelly_enabled=True)
        self._add_trades(pm, 200, mean=-0.02, seed=7)
        assert pm.kelly_cap_pct() is None

    def test_calculate_position_size_only_shrinks(self):
        from tradingagents.execution.order_models import TradeDecision, TradeAction

        decision = TradeDecision(
            action=TradeAction.BUY, ticker="X", confidence_score=0.9, quantity_pct=0.10
        )
        baseline = self._pm().calculate_position_size(decision, 100.0)

        kelly_pm = self._pm(kelly_enabled=True)
        self._add_trades(kelly_pm, 200, mean=0.005, sd=0.08, seed=11)
        with_kelly = kelly_pm.calculate_position_size(decision, 100.0)

        assert with_kelly <= baseline, "Kelly must never increase the position size"
