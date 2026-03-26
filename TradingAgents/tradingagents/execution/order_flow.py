"""Order Flow / Market Microstructure analysis module.

Pure-Python (no LLM) algorithms for analyzing exchange order book data
to determine optimal execution timing. Computes Order Book Imbalance (OBI),
detects large buy/sell walls, and produces execution signals.

Usage:
    analyzer = OrderFlowAnalyzer(config)
    signal = analyzer.get_execution_signal(order_book, side="buy")
    # signal.action -> "EXECUTE" | "WAIT" | "BLOCK"
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class WallInfo:
    """Represents a detected buy or sell wall."""
    price: float
    volume: float
    value_usd: float
    side: str  # "bid" or "ask"


@dataclass
class OrderFlowSignal:
    """Result of order flow analysis."""
    action: str  # "EXECUTE", "WAIT", "BLOCK"
    obi: float  # Order Book Imbalance (-1.0 to +1.0)
    spread: float  # Bid-ask spread as percentage
    walls: List[WallInfo]  # Detected large walls
    reason: str  # Human-readable explanation


class OrderFlowAnalyzer:
    """Analyzes order book data to produce execution timing signals.

    Designed to be used as a "Smart Guard" in ExecutionEngine — blocking
    or delaying order execution when order flow conditions are unfavorable.
    """

    def __init__(self, config: Optional[dict] = None):
        """Initialize with order_flow config block.

        Args:
            config: Dict with keys like obi_execute_threshold, obi_block_threshold,
                    order_book_depth, wall_detection_usd.
        """
        cfg = config or {}
        self.obi_execute_threshold = cfg.get("obi_execute_threshold", 0.15)
        self.obi_block_threshold = cfg.get("obi_block_threshold", -0.30)
        self.order_book_depth = cfg.get("order_book_depth", 20)
        self.wall_detection_usd = cfg.get("wall_detection_usd", 100_000)

    @staticmethod
    def calculate_obi(order_book: dict, depth: int = 20) -> float:
        """Calculate Order Book Imbalance.

        OBI = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume)

        Returns:
            Float in range [-1.0, +1.0]:
            - +1.0 = 100% buy pressure (all bids, no asks)
            - -1.0 = 100% sell pressure (all asks, no bids)
            -  0.0 = perfectly balanced
        """
        bids = order_book.get("bids", [])[:depth]
        asks = order_book.get("asks", [])[:depth]

        total_bids = sum(vol for _, vol in bids)
        total_asks = sum(vol for _, vol in asks)

        total = total_bids + total_asks
        if total == 0:
            return 0.0

        return (total_bids - total_asks) / total

    @staticmethod
    def calculate_spread(order_book: dict) -> float:
        """Calculate bid-ask spread as a percentage of mid price.

        Returns:
            Spread percentage (e.g., 0.001 = 0.1%). Returns 0.0 if
            order book has no bids/asks.
        """
        bids = order_book.get("bids", [])
        asks = order_book.get("asks", [])

        if not bids or not asks:
            return 0.0

        best_bid = bids[0][0]
        best_ask = asks[0][0]

        if best_bid <= 0:
            return 0.0

        mid = (best_bid + best_ask) / 2
        return (best_ask - best_bid) / mid

    def detect_large_walls(
        self, order_book: dict, depth: int = 20
    ) -> List[WallInfo]:
        """Detect unusually large orders ("walls") in the order book.

        A wall is a single limit order whose USD value exceeds
        `self.wall_detection_usd` threshold.

        Returns:
            List of WallInfo for each detected wall.
        """
        walls: List[WallInfo] = []

        for side_key, side_label in [("bids", "bid"), ("asks", "ask")]:
            entries = order_book.get(side_key, [])[:depth]
            for price, vol in entries:
                value_usd = price * vol
                if value_usd >= self.wall_detection_usd:
                    walls.append(WallInfo(
                        price=price,
                        volume=vol,
                        value_usd=value_usd,
                        side=side_label,
                    ))

        return walls

    def get_execution_signal(
        self, order_book: dict, side: str = "buy"
    ) -> OrderFlowSignal:
        """Analyze order book and produce an execution signal.

        Args:
            order_book: Dict with 'bids' and 'asks' from broker.
            side: Trade side — "buy" or "sell".

        Returns:
            OrderFlowSignal with action = "EXECUTE", "WAIT", or "BLOCK".

        Logic:
            For BUY orders:
            - OBI ≥ execute_threshold → EXECUTE (buyers dominate)
            - OBI ≤ block_threshold  → BLOCK (sellers dominate, dangerous)
            - Otherwise              → WAIT (neutral, hold)

            For SELL orders: thresholds are inverted.
        """
        depth = self.order_book_depth
        obi = self.calculate_obi(order_book, depth)
        spread = self.calculate_spread(order_book)
        walls = self.detect_large_walls(order_book, depth)

        # For SELL orders, invert the OBI perspective
        # (negative OBI = sell pressure = favorable for selling)
        effective_obi = obi if side.lower() == "buy" else -obi

        if effective_obi >= self.obi_execute_threshold:
            action = "EXECUTE"
            reason = (
                f"Order flow favorable for {side.upper()}: "
                f"OBI={obi:+.3f} (effective={effective_obi:+.3f}), "
                f"spread={spread:.4%}"
            )
        elif effective_obi <= self.obi_block_threshold:
            action = "BLOCK"
            wall_summary = ""
            opposing_walls = [w for w in walls if (
                (side.lower() == "buy" and w.side == "ask") or
                (side.lower() == "sell" and w.side == "bid")
            )]
            if opposing_walls:
                wall_summary = f" | {len(opposing_walls)} opposing wall(s) detected"
            reason = (
                f"Order flow DANGEROUS for {side.upper()}: "
                f"OBI={obi:+.3f} (effective={effective_obi:+.3f})"
                f"{wall_summary}"
            )
        else:
            action = "WAIT"
            reason = (
                f"Order flow neutral for {side.upper()}: "
                f"OBI={obi:+.3f} (effective={effective_obi:+.3f}), "
                f"waiting for improvement"
            )

        logger.info("[OrderFlow] %s — %s", action, reason)

        return OrderFlowSignal(
            action=action,
            obi=obi,
            spread=spread,
            walls=walls,
            reason=reason,
        )
