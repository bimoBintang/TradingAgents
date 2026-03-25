"""Geometric Chart Pattern Detection Engine.

Detects Head & Shoulders, Rising Wedge, and Falling Wedge patterns
from OHLCV DataFrame using scipy peak detection and numpy polyfit.
"""

import logging
from typing import List, Tuple

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema

logger = logging.getLogger("api.pattern_detector")


class PatternDetector:
    """Stateless pattern detector — instantiate per request."""

    # ── Peak / Trough Detection ───────────────────────────────────────

    @staticmethod
    def detect_peaks_troughs(
        closes: np.ndarray, order: int = 5
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return indices of local maxima (peaks) and minima (troughs).

        Parameters
        ----------
        closes : 1-D array of close prices.
        order  : How many points on each side to compare (default 5 for 1D).
        """
        peak_indices = argrelextrema(closes, np.greater_equal, order=order)[0]
        trough_indices = argrelextrema(closes, np.less_equal, order=order)[0]
        return peak_indices, trough_indices

    # ── Confidence Formula ────────────────────────────────────────────

    @staticmethod
    def calculate_confidence(
        symmetry: float, r_squared: float, bar_count: int
    ) -> float:
        """Weighted confidence score in [0.0 – 1.0].

        symmetry  : 0–1 (1 = perfectly symmetric shoulders / trendlines)
        r_squared : 0–1 (goodness of fit)
        bar_count : number of bars in the pattern, capped at 60
        """
        bar_score = min(bar_count / 60.0, 1.0)
        return round(symmetry * 0.4 + r_squared * 0.4 + bar_score * 0.2, 2)

    # ── Head & Shoulders ──────────────────────────────────────────────

    def detect_head_and_shoulders(
        self,
        df: pd.DataFrame,
        peak_indices: np.ndarray,
        trough_indices: np.ndarray,
    ) -> List[dict]:
        """Scan for H&S patterns among consecutive peaks.

        Validation criteria:
        1. 3 consecutive peaks (left_shoulder, head, right_shoulder)
        2. Head > both shoulders by ≥ 2 %
        3. Shoulders balanced within 5 % of head price
        4. Neckline = line through two troughs between the three peaks
        5. Inter-peak distance: 5–60 bars
        """
        results: List[dict] = []
        closes = df["close"].values
        timestamps = df["timestamp"].values  # Unix seconds

        if len(peak_indices) < 3:
            return results

        for i in range(len(peak_indices) - 2):
            li, hi, ri = peak_indices[i], peak_indices[i + 1], peak_indices[i + 2]

            # Distance constraint (5–60 bars between consecutive peaks)
            if not (5 <= (hi - li) <= 60 and 5 <= (ri - hi) <= 60):
                continue

            lp, hp, rp = closes[li], closes[hi], closes[ri]

            # Head must be higher than both shoulders by ≥ 2 %
            if hp <= lp * 1.02 or hp <= rp * 1.02:
                continue

            # Shoulders must be roughly balanced (within 5 % of head)
            if abs(lp - rp) / hp >= 0.05:
                continue

            # Find neckline troughs between left→head and head→right
            t_left_candidates = trough_indices[
                (trough_indices > li) & (trough_indices < hi)
            ]
            t_right_candidates = trough_indices[
                (trough_indices > hi) & (trough_indices < ri)
            ]

            if len(t_left_candidates) == 0 or len(t_right_candidates) == 0:
                continue

            # Pick the deepest trough in each segment
            t_left_idx = t_left_candidates[
                np.argmin(closes[t_left_candidates])
            ]
            t_right_idx = t_right_candidates[
                np.argmin(closes[t_right_candidates])
            ]

            # Confidence
            symmetry = 1.0 - abs(lp - rp) / hp  # closer shoulders → higher
            head_prominence = min((hp - lp) / hp, (hp - rp) / hp)
            r_sq = min(symmetry, head_prominence * 10)  # proxy for clarity
            r_sq = min(r_sq, 1.0)
            bar_count = ri - li
            conf = self.calculate_confidence(symmetry, r_sq, bar_count)

            results.append(
                {
                    "type": "head_and_shoulders",
                    "points": [
                        {
                            "time": int(timestamps[li]),
                            "price": float(lp),
                            "label": "left_shoulder",
                        },
                        {
                            "time": int(timestamps[hi]),
                            "price": float(hp),
                            "label": "head",
                        },
                        {
                            "time": int(timestamps[ri]),
                            "price": float(rp),
                            "label": "right_shoulder",
                        },
                        {
                            "time": int(timestamps[t_left_idx]),
                            "price": float(closes[t_left_idx]),
                            "label": "neckline_left",
                        },
                        {
                            "time": int(timestamps[t_right_idx]),
                            "price": float(closes[t_right_idx]),
                            "label": "neckline_right",
                        },
                    ],
                    "confidence": conf,
                    "direction": "bearish",
                }
            )

        return results

    # ── Wedge (generic) ───────────────────────────────────────────────

    def _detect_wedge(
        self,
        df: pd.DataFrame,
        peak_indices: np.ndarray,
        trough_indices: np.ndarray,
        rising: bool,
    ) -> List[dict]:
        """Internal: detect rising or falling wedge.

        Criteria (rising):
        - ≥3 peaks and ≥3 troughs in the same window
        - Upper and lower trendline slopes both positive
        - Lower slope steeper than upper slope * 1.1
        - R² of each fit > 0.7
        - Lines converge within 5–40 bars ahead

        Falling is the mirror image (both slopes negative, upper steeper).
        """
        results: List[dict] = []
        closes = df["close"].values
        timestamps = df["timestamp"].values

        if len(peak_indices) < 3 or len(trough_indices) < 3:
            return results

        # Slide a window across the data: try different starting points
        min_window = 20
        max_window = min(120, len(df))

        for win_start in range(0, len(df) - min_window, 10):
            for win_len in range(min_window, min(max_window, len(df) - win_start) + 1, 15):
                win_end = win_start + win_len

                # Peaks and troughs inside this window
                wp = peak_indices[
                    (peak_indices >= win_start) & (peak_indices < win_end)
                ]
                wt = trough_indices[
                    (trough_indices >= win_start) & (trough_indices < win_end)
                ]

                if len(wp) < 3 or len(wt) < 3:
                    continue

                # Fit upper trendline through peaks
                x_peaks = wp.astype(float)
                y_peaks = closes[wp]
                coeff_upper = np.polyfit(x_peaks, y_peaks, 1)
                slope_upper = coeff_upper[0]

                # Fit lower trendline through troughs
                x_troughs = wt.astype(float)
                y_troughs = closes[wt]
                coeff_lower = np.polyfit(x_troughs, y_troughs, 1)
                slope_lower = coeff_lower[0]

                # R² for both fits
                r2_upper = self._r_squared(x_peaks, y_peaks, coeff_upper)
                r2_lower = self._r_squared(x_troughs, y_troughs, coeff_lower)

                if r2_upper < 0.7 or r2_lower < 0.7:
                    continue

                if rising:
                    # Rising wedge: both slopes positive, lower steeper
                    if slope_upper <= 0 or slope_lower <= 0:
                        continue
                    if slope_lower <= slope_upper * 1.1:
                        continue
                    direction = "bearish"
                    pattern_type = "rising_wedge"
                else:
                    # Falling wedge: both slopes negative, upper steeper (more negative)
                    if slope_upper >= 0 or slope_lower >= 0:
                        continue
                    if slope_upper >= slope_lower * 1.1:
                        continue
                    direction = "bullish"
                    pattern_type = "falling_wedge"

                # Convergence check: lines should meet within 5–40 bars ahead
                if abs(slope_upper - slope_lower) < 1e-9:
                    continue
                bars_to_converge = (
                    coeff_lower[1] - coeff_upper[1]
                ) / (slope_upper - slope_lower) - win_end
                if not (5 <= bars_to_converge <= 40):
                    continue

                # Build result points
                upper_start_idx = int(wp[0])
                upper_end_idx = int(wp[-1])
                lower_start_idx = int(wt[0])
                lower_end_idx = int(wt[-1])

                symmetry = min(r2_upper, r2_lower)
                r_sq = (r2_upper + r2_lower) / 2
                bar_count = max(upper_end_idx, lower_end_idx) - min(
                    upper_start_idx, lower_start_idx
                )
                conf = self.calculate_confidence(symmetry, r_sq, bar_count)

                results.append(
                    {
                        "type": pattern_type,
                        "points": [
                            {
                                "time": int(timestamps[upper_start_idx]),
                                "price": float(
                                    np.polyval(coeff_upper, upper_start_idx)
                                ),
                                "label": "upper_start",
                            },
                            {
                                "time": int(timestamps[upper_end_idx]),
                                "price": float(
                                    np.polyval(coeff_upper, upper_end_idx)
                                ),
                                "label": "upper_end",
                            },
                            {
                                "time": int(timestamps[lower_start_idx]),
                                "price": float(
                                    np.polyval(coeff_lower, lower_start_idx)
                                ),
                                "label": "lower_start",
                            },
                            {
                                "time": int(timestamps[lower_end_idx]),
                                "price": float(
                                    np.polyval(coeff_lower, lower_end_idx)
                                ),
                                "label": "lower_end",
                            },
                        ],
                        "confidence": conf,
                        "direction": direction,
                    }
                )

        # De-duplicate overlapping patterns: keep highest confidence
        results = self._deduplicate(results)
        return results

    def detect_rising_wedge(
        self,
        df: pd.DataFrame,
        peak_indices: np.ndarray,
        trough_indices: np.ndarray,
    ) -> List[dict]:
        """Public API: detect rising wedge patterns."""
        return self._detect_wedge(df, peak_indices, trough_indices, rising=True)

    def detect_falling_wedge(
        self,
        df: pd.DataFrame,
        peak_indices: np.ndarray,
        trough_indices: np.ndarray,
    ) -> List[dict]:
        """Public API: detect falling wedge patterns."""
        return self._detect_wedge(df, peak_indices, trough_indices, rising=False)

    # ── Convenience: run all detectors ────────────────────────────────

    def detect_all(self, df: pd.DataFrame, order: int = 5) -> List[dict]:
        """Run all pattern detectors and return merged list."""
        closes = df["close"].values
        peaks, troughs = self.detect_peaks_troughs(closes, order=order)
        results: List[dict] = []
        results.extend(self.detect_head_and_shoulders(df, peaks, troughs))
        results.extend(self.detect_rising_wedge(df, peaks, troughs))
        results.extend(self.detect_falling_wedge(df, peaks, troughs))
        return results

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _r_squared(x: np.ndarray, y: np.ndarray, coeffs: np.ndarray) -> float:
        """Compute R² for a polynomial fit."""
        y_pred = np.polyval(coeffs, x)
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        if ss_tot == 0:
            return 0.0
        return max(0.0, 1.0 - ss_res / ss_tot)

    @staticmethod
    def _deduplicate(patterns: List[dict], overlap_threshold: int = 10) -> List[dict]:
        """Remove overlapping patterns, keeping the highest confidence."""
        if not patterns:
            return patterns
        # Sort by confidence DESC
        patterns.sort(key=lambda p: p["confidence"], reverse=True)
        kept: List[dict] = []
        used_times: set = set()
        for p in patterns:
            times = frozenset(pt["time"] for pt in p["points"])
            if len(times & used_times) > overlap_threshold:
                continue
            kept.append(p)
            used_times |= times
        return kept
