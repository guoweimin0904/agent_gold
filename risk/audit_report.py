"""Risk audit output model — the exact JSON format for audit results."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass
class AuditCheckResult:
    """Result of a single audit check."""
    check_id: str                # e.g. "over_optimism", "news_reliability"
    check_name: str              # Human-readable name
    passed: bool
    severity: Literal["info", "warning", "critical"] = "info"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskAuditReport:
    """
    Risk audit report — output of RiskAuditAgent.

    The agent's job is NOT to propose trades, but to **refute** the main decision.
    """

    approved: bool = False
    risk_level: RiskLevel = "low"
    veto_reason: str = ""
    position_limit: str = ""
    required_checks: list[str] = field(default_factory=list)
    check_results: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    symbol: str = ""
    final_score: float = 0.0
    direction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "risk_level": self.risk_level,
            "veto_reason": self.veto_reason,
            "position_limit": self.position_limit,
            "required_checks": self.required_checks,
            "check_results": self.check_results,
            "generated_at": self.generated_at,
            "symbol": self.symbol,
            "final_score": self.final_score,
            "direction": self.direction,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def disclaimer() -> str:
        return "⚠️ 风控审查仅用于风险控制，不构成交易建议。审查通过不代表交易必然盈利。"
