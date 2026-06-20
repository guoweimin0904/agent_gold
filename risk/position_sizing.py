"""Position sizing — calculate trade size based on volatility & risk tolerance."""

from decimal import Decimal
from typing import Any

import numpy as np


class PositionSizer:
    """Dynamic position sizing using volatility-adjusted allocation."""

    def __init__(
        self,
        max_risk_pct: float = 0.02,  # risk 2% of capital per trade
        base_capital: float = 10_000.0,
    ) -> None:
        self.max_risk_pct = max_risk_pct
        self.base_capital = base_capital

    def kelly_fraction(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
    ) -> float:
        """Kelly Criterion — optimal fraction to risk."""
        if avg_loss == 0:
            return 0.0
        b = avg_win / avg_loss  # odds
        p = win_rate
        q = 1 - p
        kelly = (b * p - q) / b
        return max(0.0, min(kelly, 0.25))  # cap at 25%

    def volatility_adjusted_size(
        self,
        capital: float,
        price: Decimal,
        atr: float,
        risk_pct: float | None = None,
    ) -> Decimal:
        """
        Calculate position size based on ATR volatility.
        Smaller size when volatility is high.
        """
        risk = risk_pct or self.max_risk_pct
        risk_amount = capital * risk
        if atr == 0 or price == 0:
            return Decimal("0")

        # Stop distance = 1.5 * ATR
        stop_distance = Decimal(str(atr * 1.5))
        size = Decimal(str(risk_amount)) / stop_distance
        max_qty = Decimal(str(capital * 0.5)) / price  # don't use >50% of capital
        return min(size, max_qty).quantize(Decimal("0.00001"))

    def scale_into_position(
        self,
        total_size: Decimal,
        num_entries: int = 3,
    ) -> list[tuple[Decimal, str]]:
        """Scale into a position over multiple entries."""
        if num_entries <= 0:
            return []
        portions = []
        sizes = np.linspace(0.3, 0.4, num_entries)  # e.g. 30%, 35%, 35%
        sizes = sizes / sizes.sum()
        for i, pct in enumerate(sizes):
            portion = (total_size * Decimal(str(pct))).quantize(Decimal("0.00001"))
            portions.append((portion, f"entry_{i + 1}"))
        return portions
