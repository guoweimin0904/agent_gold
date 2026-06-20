"""Paper trading — simulate trades without real money."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from analysis.decision_schema import TradingDecision

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class PaperPosition:
    symbol: str
    side: str  # long / short
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    pnl: Decimal = Decimal("0")


class PaperTrade:
    """Paper trading engine — tracks positions and simulates PnL."""

    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self.balance = Decimal(str(initial_balance))
        self.positions: dict[str, PaperPosition] = {}
        self._trade_log: list[dict[str, Any]] = []
        self._log_path = DATA_DIR / "paper_trades.json"

    def execute(self, decision: TradingDecision, current_price: Decimal) -> dict[str, Any]:
        """Execute a paper trade based on a TradingDecision."""
        if decision.action == "hold":
            return {"status": "no_action", "reason": decision.reason}

        quantity = (self.balance * Decimal(str(decision.quantity_pct / 100))) / current_price
        quantity = quantity.quantize(Decimal("0.00001"))

        if decision.action == "buy":
            cost = quantity * current_price
            if cost > self.balance:
                return {"status": "rejected", "reason": "Insufficient balance"}

            self.balance -= cost
            self.positions[decision.symbol] = PaperPosition(
                symbol=decision.symbol,
                side="long",
                entry_price=current_price,
                quantity=quantity,
                entry_time=datetime.now(timezone.utc),
                stop_loss=decision.stop_loss,
                take_profit=decision.price_target,
            )

        elif decision.action == "sell" and decision.symbol in self.positions:
            pos = self.positions.pop(decision.symbol)
            proceeds = quantity * current_price
            self.balance += proceeds
            pos.pnl = (current_price - pos.entry_price) * pos.quantity

        trade_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": decision.action,
            "symbol": decision.symbol,
            "price": str(current_price),
            "quantity": str(quantity),
            "balance": str(self.balance),
            "reason": decision.reason,
        }
        self._trade_log.append(trade_record)
        self._persist()

        return {"status": "executed", **trade_record}

    def _persist(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "w") as f:
            json.dump(self._trade_log, f, indent=2, ensure_ascii=False)

    @property
    def total_equity(self) -> float:
        positions_value = sum(p.quantity * p.entry_price for p in self.positions.values())
        return float(self.balance + Decimal(str(positions_value)))

    def summary(self) -> dict[str, Any]:
        return {
            "balance": float(self.balance),
            "open_positions": len(self.positions),
            "total_equity": self.total_equity,
            "total_trades": len(self._trade_log),
        }
