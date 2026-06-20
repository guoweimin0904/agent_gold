"""Scoring schemas — the exact output contract for the scoring engine."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

Market = Literal["crypto", "a_stock"]
Decision = Literal["avoid", "watch", "candidate", "strong_candidate"]
Confidence = Literal["high", "medium", "low"]


@dataclass
class SubScores:
    """7 sub-dimension scores. Each is 0-100."""

    event_score: float = 0.0       # news / event impact
    sentiment_score: float = 0.0   # social / news sentiment
    kline_score: float = 0.0       # k-line pattern / price action
    technical_score: float = 0.0   # indicator confluence (RSI, MACD, MA, BB)
    fund_flow_score: float = 0.0   # volume / whale / exchange flow
    backtest_score: float = 0.0    # historical strategy performance
    risk_deduction: float = 0.0    # penalty from risk module (0-100, deducted)

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @property
    def raw_total(self) -> float:
        """Sum before risk deduction (max 600)."""
        return (
            self.event_score
            + self.sentiment_score
            + self.kline_score
            + self.technical_score
            + self.fund_flow_score
            + self.backtest_score
        )


@dataclass
class VetoInfo:
    """Veto record — who vetoed and why."""

    vetoed: bool = False
    vetoed_by: str = ""             # "validator_agent" | "risk_control" | "kill_switch"
    reason: str = ""


@dataclass
class ScoredDimension:
    """Detailed breakdown of one sub-score."""
    name: str
    score: float
    weight: float
    reason: str = ""
    data_available: bool = True
    data_missing: bool = False


@dataclass
class ScoringReport:
    """
    Complete scoring output — the exact JSON requested.

    Requirements:
      - 总分 ≥ 80 → strong_candidate
      - 70-80  → candidate
      - 60-70  → watch
      - < 60   → avoid (禁止交易)
      - 副模型/风控否决时，即使总分高也不能执行
    """

    # ── Identity ──
    market: Market = "crypto"
    symbol: str = ""
    timeframe: str = "1h"
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Scores ──
    scores: SubScores = field(default_factory=SubScores)
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    final_score: float = 0.0

    # ── Decision ──
    decision: Decision = "avoid"
    confidence: float = 0.0
    need_human_confirm: bool = True

    # ── Veto ──
    veto: VetoInfo = field(default_factory=VetoInfo)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at,
            "scores": self.scores.to_dict(),
            "dimensions": self.dimensions,
            "final_score": round(self.final_score, 1),
            "decision": self.decision,
            "confidence": round(self.confidence, 2),
            "need_human_confirm": self.need_human_confirm,
            "veto": asdict(self.veto),
            "reason": self.reason,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 评分结果仅供研究参考，不构成任何投资建议。"
            "评分基于历史数据和当前市场状态，不代表未来表现。"
            "副模型或风控层否决时，即使总分高也不能执行。"
        )

    def update_decision(self) -> None:
        """Recompute decision from final_score."""
        if self.veto.vetoed:
            self.decision = "avoid"
            self.confidence = 0.0
            self.need_human_confirm = True
            self.reason = f"被 {self.veto.vetoed_by} 否决: {self.veto.reason}"
            return

        fs = self.final_score
        if fs >= 80:
            self.decision = "strong_candidate"
            self.confidence = min(fs / 100, 0.95)
            self.need_human_confirm = fs < 90  # >= 90 still need human for critical
        elif fs >= 70:
            self.decision = "candidate"
            self.confidence = fs / 100
            self.need_human_confirm = True
        elif fs >= 60:
            self.decision = "watch"
            self.confidence = fs / 100 * 0.8
            self.need_human_confirm = True
        else:
            self.decision = "avoid"
            self.confidence = 0.0
            self.need_human_confirm = False  # auto-avoid, no human needed
            self.reason = f"总分 {fs:.1f} < 60，禁止交易"
