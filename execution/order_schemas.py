"""Order plan — the output of ExecutionGate after all checks pass.

Only emitted when ALL 7 security checks pass.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

ExecutionMode = Literal["paper", "testnet", "real"]
Direction = Literal["long", "short"]
OrderType = Literal["market", "limit"]


@dataclass
class OrderPlan:
    """
    Final executable order plan. Only created when ExecutionGate approves.

    All order-related fields are only populated when approved=True.
    """

    # ── Approval ──
    approved: bool = False
    execution_mode: ExecutionMode = "paper"
    reject_reason: str = ""
    reject_details: list[dict[str, Any]] = field(default_factory=list)

    # ── Identity ──
    symbol: str = ""
    direction: Direction = "long"
    order_type: OrderType = "market"

    # ── Order params ──
    quantity: float = 0.0               # units
    quantity_usdt: float = 0.0           # USDT value
    price: float | None = None           # for limit orders

    # ── Risk ──
    stop_loss: str = ""
    invalid_condition: str = ""
    position_pct: float = 0.0            # % of capital

    # ── Provenance ──
    decision_id: str = ""
    final_score: float = 0.0
    confidence: float = 0.0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "execution_mode": self.execution_mode,
            "reject_reason": self.reject_reason,
            "reject_details": self.reject_details,
            "symbol": self.symbol,
            "direction": self.direction,
            "order_type": self.order_type,
            "quantity": round(self.quantity, 6),
            "quantity_usdt": round(self.quantity_usdt, 2),
            "price": round(self.price, 2) if self.price is not None else None,
            "stop_loss": self.stop_loss,
            "invalid_condition": self.invalid_condition,
            "position_pct": round(self.position_pct, 1),
            "decision_id": self.decision_id,
            "final_score": round(self.final_score, 1),
            "confidence": round(self.confidence, 2),
            "generated_at": self.generated_at,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def rejected(
        reason: str,
        details: list[dict[str, Any]] | None = None,
        mode: str = "paper",
    ) -> "OrderPlan":
        return OrderPlan(
            approved=False,
            execution_mode=mode,  # type: ignore
            reject_reason=reason,
            reject_details=details or [],
        )

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 订单计划仅基于当前市场条件和风控规则生成。"
            "实际成交价可能因滑点、流动性等因素偏离计划价格。"
            "即使计划通过，交易仍存在亏损风险。"
        )
