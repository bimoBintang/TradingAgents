"""Backtest report generator.

Produces a markdown report with metrics tables, per-trade detail,
and confidence calibration analysis.
"""

import os
from datetime import datetime
from typing import Optional

from .metrics import BacktestMetrics


def generate_report(
    metrics: BacktestMetrics,
    ticker: str,
    start_date: str,
    end_date: str,
    output_dir: Optional[str] = None,
) -> str:
    """Generate a comprehensive markdown backtest report.

    Args:
        metrics: Computed BacktestMetrics
        ticker: Ticker that was backtested
        start_date: Start of backtest range
        end_date: End of backtest range
        output_dir: Directory to save report file (optional)

    Returns:
        Markdown report string
    """
    lines = []

    # Header
    lines.append(f"# Backtest Report: {ticker}")
    lines.append(f"**Period**: {start_date} to {end_date}")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Trading Days**: {metrics.total_days}")
    lines.append("")

    # Decision Distribution
    lines.append("## Decision Distribution")
    lines.append("")
    lines.append("| Decision | Count | % |")
    lines.append("|----------|-------|---|")
    total = max(metrics.total_days, 1)
    lines.append(f"| BUY  | {metrics.buy_count}  | {metrics.buy_count / total * 100:.1f}% |")
    lines.append(f"| SELL | {metrics.sell_count} | {metrics.sell_count / total * 100:.1f}% |")
    lines.append(f"| HOLD | {metrics.hold_count} | {metrics.hold_count / total * 100:.1f}% |")
    lines.append("")

    # Key Metrics
    lines.append("## Key Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Directional Accuracy | **{metrics.directional_accuracy:.1f}%** |")
    lines.append(f"| Win Rate | {metrics.win_rate:.1f}% |")
    lines.append(f"| Total Return | {metrics.total_return_pct:+.2f}% |")
    lines.append(f"| Avg Return/Trade | {metrics.avg_return_per_trade_pct:+.3f}% |")
    lines.append(f"| Best Trade | {metrics.best_trade_pct:+.2f}% |")
    lines.append(f"| Worst Trade | {metrics.worst_trade_pct:+.2f}% |")
    pf_str = f"{metrics.profit_factor:.2f}" if metrics.profit_factor != float("inf") else "INF"
    lines.append(f"| Profit Factor | {pf_str} |")
    lines.append(f"| Sharpe Ratio | {metrics.sharpe_ratio:.2f} |")
    lines.append(f"| Max Drawdown | {metrics.max_drawdown_pct:.2f}% |")
    lines.append("")

    # Exit-rule breakdown — separates "the signal was right" from "the
    # stop/target placement happened to be lucky". A strategy whose
    # profits come almost entirely from take-profit hits is a different
    # (and more fragile) animal than one that wins on time exits.
    lines.append("## How Positions Closed")
    lines.append("")
    lines.append("| Exit Reason | Count |")
    lines.append("|-------------|-------|")
    lines.append(f"| Stop-Loss | {metrics.stop_loss_exits} |")
    lines.append(f"| Take-Profit | {metrics.take_profit_exits} |")
    lines.append(f"| Time / Horizon | {metrics.time_exits} |")
    lines.append(f"| Avg Holding Period | {metrics.avg_holding_days:.1f} days |")
    lines.append("")

    # Confidence Calibration
    lines.append("## Confidence Calibration")
    lines.append("")
    lines.append("| Category | Avg Confidence |")
    lines.append("|----------|----------------|")
    lines.append(f"| All Trades | {metrics.avg_confidence:.2f} |")
    lines.append(f"| Correct Calls | {metrics.avg_confidence_correct:.2f} |")
    lines.append(f"| Incorrect Calls | {metrics.avg_confidence_incorrect:.2f} |")
    gap = metrics.avg_confidence_correct - metrics.avg_confidence_incorrect
    lines.append("")
    if gap > 0.05:
        lines.append(f"> Model is somewhat calibrated: correct trades have {gap:.0%} higher confidence.")
    elif gap < -0.05:
        lines.append(f"> **WARNING**: Model is ANTI-calibrated! Incorrect calls have higher confidence.")
    else:
        lines.append("> Model confidence does not meaningfully distinguish correct from incorrect trades.")
    lines.append("")

    # Per-Trade Detail
    lines.append("## Trade Log")
    lines.append("")
    lines.append("| Entry | Decision | Conf | Size | Entry $ | Exit $ | Exit | Held | Net Return | Correct |")
    lines.append("|-------|----------|------|------|---------|--------|------|------|------------|---------|")
    for t in metrics.trades:
        correct_str = ""
        if t.direction_correct is True:
            correct_str = "YES"
        elif t.direction_correct is False:
            correct_str = "NO"
        else:
            correct_str = "-"

        lines.append(
            f"| {t.date} | {t.decision} | {t.confidence:.2f} "
            f"| {t.quantity_pct * 100:.0f}% "
            f"| ${t.entry_price:.2f} | ${t.exit_price:.2f} "
            f"| {t.exit_reason} | {t.holding_days}d "
            f"| {t.strategy_return_pct:+.2f}% | {correct_str} |"
        )
    lines.append("")

    report = "\n".join(lines)

    # Save to file if output_dir specified
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"backtest_{ticker}_{start_date}_to_{end_date}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

    return report
