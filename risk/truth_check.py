"""Truth check — validate data integrity and flag anomalies before decision-making."""

from decimal import Decimal
from typing import Any

import pandas as pd


class TruthCheck:
    """Validate incoming market data for integrity & consistency."""

    @staticmethod
    def check_ohlcv(df: pd.DataFrame) -> list[str]:
        """Run basic sanity checks on OHLCV data. Returns list of issues."""
        issues: list[str] = []

        if df.empty:
            issues.append("Empty DataFrame")
            return issues

        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            issues.append(f"Missing columns: {missing}")

        for col in required_cols & set(df.columns):
            if df[col].isna().any():
                issues.append(f"NaN values in '{col}'")
            if (df[col] <= 0).any():
                issues.append(f"Non-positive values in '{col}'")

        # High >= Low
        if {"high", "low"}.issubset(df.columns):
            if (df["high"] < df["low"]).any():
                issues.append("High < Low in some rows")

        # Price jumps > 50%
        if "close" in df.columns:
            pct_change = df["close"].pct_change().abs()
            large_jumps = pct_change > 0.5
            if large_jumps.any():
                count = large_jumps.sum()
                issues.append(f"{count} rows with >50% price jump (possible data error)")

        return issues

    @staticmethod
    def check_news_item(item: dict[str, Any]) -> list[str]:
        """Validate a single news item."""
        issues = []
        if not item.get("title"):
            issues.append("Empty title")
        if not item.get("url"):
            issues.append("Missing URL")
        return issues
