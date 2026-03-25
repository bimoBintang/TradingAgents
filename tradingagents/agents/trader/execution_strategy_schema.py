"""Pydantic v2 validation model for the Execution Optimizer's output.

Parses and validates the <EXECUTION_STRATEGY> JSON block produced by the LLM.
"""

from __future__ import annotations

import re
import json
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class LadderEntry(BaseModel):
    """A single entry in a DCA/ladder execution plan."""
    price: float = Field(..., gt=0, description="Entry price level")
    pct_of_total: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of total order to place at this level"
    )


class ExecutionStrategy(BaseModel):
    """Validated execution strategy from the Execution Optimizer agent."""

    entry_timing: str = Field(
        default="market hours",
        description="Optimal entry window description"
    )
    order_type: Literal["MARKET", "LIMIT"] = Field(default="MARKET")
    limit_price: Optional[float] = Field(
        default=None, ge=0,
        description="Limit price (required when order_type=LIMIT)"
    )
    ladder_entries: list[LadderEntry] = Field(
        default_factory=list,
        description="DCA ladder entries"
    )
    execution_method: Literal["SINGLE", "TWAP", "VWAP", "DCA"] = Field(
        default="SINGLE"
    )
    refined_stop_loss_pct: float = Field(
        default=0.05, ge=0.001, le=0.50,
        description="Volatility-adjusted stop loss %"
    )
    refined_take_profit_pct: float = Field(
        default=0.10, ge=0.005, le=1.0,
        description="Volatility-adjusted take profit %"
    )
    atr_based_stop: Optional[float] = Field(
        default=None, ge=0,
        description="ATR-based stop distance in absolute price"
    )
    max_slippage_tolerance_pct: float = Field(
        default=0.005, ge=0.0, le=0.10,
        description="Maximum acceptable slippage"
    )
    urgency: Literal["LOW", "MEDIUM", "HIGH"] = Field(default="MEDIUM")
    notes: str = Field(default="", max_length=500)

    # ── Validators ────────────────────────────────────────────────────

    @field_validator("limit_price")
    @classmethod
    def limit_price_required_for_limit_orders(cls, v, info):
        """Limit price must be set when order_type is LIMIT."""
        # This runs after field parsing; cross-field check in model_validator
        return v

    @model_validator(mode="after")
    def validate_cross_fields(self) -> "ExecutionStrategy":
        """Cross-field validation rules."""
        # Limit orders require a price
        if self.order_type == "LIMIT" and self.limit_price is None:
            self.order_type = "MARKET"  # Fallback gracefully

        # DCA method requires ladder entries
        if self.execution_method == "DCA" and not self.ladder_entries:
            self.execution_method = "SINGLE"

        # Ladder entries should sum to ~1.0
        if self.ladder_entries:
            total = sum(e.pct_of_total for e in self.ladder_entries)
            if not (0.95 <= total <= 1.05):
                # Normalize
                for entry in self.ladder_entries:
                    entry.pct_of_total = round(entry.pct_of_total / total, 4)

        # Risk/reward sanity: take_profit should be > stop_loss
        if self.refined_take_profit_pct < self.refined_stop_loss_pct:
            self.refined_take_profit_pct, self.refined_stop_loss_pct = (
                self.refined_stop_loss_pct,
                self.refined_take_profit_pct,
            )

        return self


# ── Parser ────────────────────────────────────────────────────────────

_STRATEGY_PATTERN = re.compile(
    r"<EXECUTION_STRATEGY>\s*(.*?)\s*</EXECUTION_STRATEGY>",
    re.DOTALL,
)


def parse_execution_strategy(raw_output: str) -> ExecutionStrategy | None:
    """Extract and validate the <EXECUTION_STRATEGY> JSON from LLM output.

    Returns a validated ExecutionStrategy or None if parsing/validation fails.
    Falls back to defaults for missing fields.
    """
    match = _STRATEGY_PATTERN.search(raw_output)
    if not match:
        return None

    json_str = match.group(1).strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    try:
        return ExecutionStrategy.model_validate(data)
    except Exception:
        # Return safe defaults rather than crashing
        return ExecutionStrategy()
