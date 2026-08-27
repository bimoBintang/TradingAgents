"""Data Quality Guard for TradingAgents.

Validates the integrity, staleness, and completeness of data fetched
from external APIs (e.g., yfinance, alpha_vantage) before feeding it
into the LLM agents.
"""

import logging
import re
from datetime import datetime
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)


class DataValidator:
    """Validates raw data and assigns a Data Quality Score (0.0 to 1.0)."""

    def __init__(self):
        # We can add configuration options here if needed later
        pass

    def _extract_date(self, text: str) -> datetime:
        """Attempt to extract the most recent date from text.
        
        Looks for standard YYYY-MM-DD patterns.
        Returns epoch 0 datetime if no date found.
        """
        match = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d")
            except ValueError:
                pass
        return datetime(1970, 1, 1)

    def validate_price_data(self, data_str: str, target_date: str, ticker: str = "") -> Tuple[float, str]:
        """Validate historical price data / indicators.
        
        Args:
            data_str: Raw data string from dataflow
            target_date: The date this data is supposedly for (YYYY-MM-DD)
            ticker: Ticker symbol to determine asset class (e.g., crypto vs tradfi)
            
        Returns:
            Tuple of (quality_score, report)
        """
        issues = []
        score = 1.0

        if not data_str or "No data found" in data_str or "Error" in data_str:
            return 0.0, "FATAL: Data is missing or API error occurred."

        # Check for completeness (basic heuristics)
        if "Close" not in data_str and "close" not in data_str and ":" not in data_str:
            score -= 0.3
            issues.append("Missing expected 'Close' price fields.")

        # Check staleness
        extracted_date = self._extract_date(data_str)
        target_dt = datetime.strptime(target_date, "%Y-%m-%d")
        
        if extracted_date > datetime(1970, 1, 1):
            days_diff = (target_dt - extracted_date).days
            
            # Crypto markets are 24/7. No weekends or holidays.
            is_crypto = "-USD" in ticker.upper() or ticker.upper() in ["BTC", "ETH", "SOL"]
            
            if is_crypto:
                if days_diff > 2:
                    score -= 0.6
                    issues.append(f"STALE CRYPTO: Data is {days_diff} days old. Crypto operates 24/7.")
                elif days_diff > 1:
                    score -= 0.3
                    issues.append(f"Slightly stale crypto data ({days_diff} days old).")
            else:
                # TradFi stocks: Stock market is closed on weekends, so up to 4-5 days could be normal for holidays
                if days_diff > 5:
                    score -= 0.5
                    issues.append(f"STALE: Data is {days_diff} days older than target date.")
                elif days_diff > 3:
                    score -= 0.2
                    issues.append(f"Slightly stale data ({days_diff} days old).")

        # Sanity check: is there a massive price gap? (We'd need to parse the CSV/text for this,
        # but for now we rely on the above checks. In production we'd parse and check anomalies.)

        report = "Valid" if not issues else " | ".join(issues)
        return max(0.0, score), report

    def validate_fundamentals(self, data_str: str) -> Tuple[float, str]:
        """Validate company fundamentals data."""
        issues = []
        score = 1.0

        if not data_str or "No fundamentals" in data_str or "Error" in data_str:
            return 0.0, "FATAL: Fundamentals missing or API error."

        required_fields = ["Market Cap", "PE Ratio", "Beta"]
        missing = [f for f in required_fields if f not in data_str]
        
        if missing:
            penalty = len(missing) * 0.15
            score -= penalty
            issues.append(f"Missing fields: {', '.join(missing)}.")

        report = "Valid" if not issues else " | ".join(issues)
        return max(0.0, score), report

    def get_overall_quality(
        self, 
        price_data: str, 
        fundamentals: str, 
        target_date: str,
        ticker: str = ""
    ) -> Dict[str, Any]:
        """Validate multiple data streams and compute an overall score.
        
        Returns:
            Dict containing scores and warnings.
        """
        price_score, price_report = self.validate_price_data(price_data, target_date, ticker)
        fund_score, fund_report = self.validate_fundamentals(fundamentals)

        overall_score = (price_score * 0.7) + (fund_score * 0.3)
        
        return {
            "score": round(overall_score, 2),
            "price_quality": {"score": price_score, "report": price_report},
            "fundamentals_quality": {"score": fund_score, "report": fund_report},
            "is_actionable": overall_score >= 0.5,
            "summary_warning": (
                "" if overall_score >= 0.8 else
                "WARNING: Data quality is compromised. Exercise caution."
            )
        }
