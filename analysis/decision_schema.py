"""Decision schema — the structured output format for LLM-driven trading decisions."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

Action = Literal["buy", "sell", "hold"]
Confidence = Literal["high", "medium", "low"]


@dataclass
class TradingDecision:
    symbol: str
    action: Action = "hold"
    confidence: Confidence = "low"
    quantity_pct: float = 0.0  # % of available capital (0–100)
    reason: str = ""
    price_target: Decimal | None = None
    stop_loss: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.action not in ("buy", "sell", "hold"):
            errors.append(f"Invalid action: {self.action}")
        if self.action != "hold" and not (0 < self.quantity_pct <= 100):
            errors.append(f"quantity_pct must be 0–100, got {self.quantity_pct}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "quantity_pct": self.quantity_pct,
            "reason": self.reason,
            "price_target": str(self.price_target) if self.price_target else None,
            "stop_loss": str(self.stop_loss) if self.stop_loss else None,
        }
