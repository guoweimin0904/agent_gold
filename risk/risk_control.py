"""Risk control — position sizing, max loss limits, portfolio-level checks."""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from config import RiskConfig

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class DailyLossTracker:
    """Tracks cumulative PnL and enforces daily loss limits."""

    def __init__(self, max_loss_usdt: float = 200.0) -> None:
        self.max_loss = max_loss_usdt
        self._today = dt.date.today()
        self._pnl: float = 0.0
        self._log_path = LOG_DIR / "risk.log"

    def record_trade(self, pnl: float) -> None:
        """Record a trade's PnL contribution."""
        now = dt.datetime.now()
        if now.date() != self._today:
            # Reset daily
            self._today = now.date()
            self._pnl = 0.0
        self._pnl += pnl
        self._persist()

    @property
    def remaining_budget(self) -> float:
        """Remaining daily loss budget."""
        return self.max_loss - self._pnl

    @property
    def is_stopped(self) -> bool:
        """True if daily loss limit is exceeded."""
        return self._pnl <= -self.max_loss

    def _persist(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a") as f:
            f.write(
                json.dumps({
                    "timestamp": dt.datetime.now().isoformat(),
                    "daily_pnl": round(self._pnl, 2),
                    "remaining_budget": round(self.remaining_budget, 2),
                    "stopped": self.is_stopped,
                })
                + "\n"
            )


class RiskController:
    """Portfolio-level risk checks before executing any trade."""

    def __init__(self, config_: RiskConfig | None = None) -> None:
        self.cfg = config_ or RiskConfig()
        self.loss_tracker = DailyLossTracker(max_loss_usdt=self.cfg.max_daily_loss_usdt)

    def check_order(
        self,
        symbol: str,
        side: str,
        quantity_usdt: float,
        current_positions: dict[str, float],
    ) -> tuple[bool, str]:
        """
        Check if an order is permissible.

        Returns (approved: bool, reason: str).
        """
        # Daily loss stop
        if self.loss_tracker.is_stopped:
            return False, "Daily loss limit reached — trading halted"

        # Position size limit
        if quantity_usdt > self.cfg.max_position_size_usdt:
            return False, (
                f"Position size {quantity_usdt:.2f} USDT exceeds "
                f"max {self.cfg.max_position_size_usdt:.2f} USDT"
            )

        # Concentrated position check
        total_exposure = sum(current_positions.values())
        if side == "buy" and total_exposure > 0:
            new_exposure = total_exposure + quantity_usdt
            if symbol in current_positions:
                weight = (current_positions[symbol] + quantity_usdt) / new_exposure
            else:
                weight = quantity_usdt / new_exposure
            if weight > 0.4:
                return False, f"{symbol} would exceed 40% portfolio concentration"

        return True, "OK"
