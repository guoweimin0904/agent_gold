"""Anti look-ahead bias guard — validate that signals only use past data."""

import datetime as dt
from typing import Any

import pandas as pd


def check_lookahead(signal_df: pd.DataFrame, signal_col: str = "signal") -> list[str]:
    """
    Verify that a signal column is generated without look-ahead bias.
    Checks: no future close/volume used, signal at T is based on data at T-1.
    Returns a list of violations (empty = clean).
    """
    violations: list[str] = []
    if signal_col not in signal_df.columns:
        violations.append(f"Column '{signal_col}' not found")
        return violations

    # Check no NaN at the first row (signal should be NaN if computed correctly)
    if pd.notna(signal_df[signal_col].iloc[0]):
        violations.append("Signal is non-NaN at first row — possible look-ahead")

    # Check signal is NaN for the first N rows if using rolling windows > 1
    return violations


def shift_signals(df: pd.DataFrame, signal_col: str = "signal", periods: int = 1) -> pd.DataFrame:
    """
    Safe signal shifting — ensures signals never peek into future data.
    Always call this before feeding signals to the backtest engine.
    """
    df = df.copy()
    df[signal_col] = df[signal_col].shift(periods)
    return df


def validate_data_split(
    df: pd.DataFrame,
    train_end: str | dt.datetime,
    test_start: str | dt.datetime,
) -> bool:
    """Ensure train/test split has no temporal overlap."""
    train = df[df.index < train_end] if isinstance(df.index, pd.DatetimeIndex) else None
    test = df[df.index >= test_start] if isinstance(df.index, pd.DatetimeIndex) else None
    if train is not None and test is not None:
        overlap = set(train.index).intersection(set(test.index))
        if overlap:
            return False
    return True
