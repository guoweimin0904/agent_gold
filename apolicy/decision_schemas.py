"""Policy analysis output schema — the exact structured output for A-Share policy events.

Requirements:
1. 判断政策来源
2. 判断政策级别
3. 判断政策类型
4. 判断受益方向和受损方向
5. 判断时间周期
6. 判断市场是否已反应
7. 政策交易价值评分（<60 不得交易）
8. 来源不可靠或信息不完整 → 需要验证，不可交易
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

SourceType = Literal[
    "国务院", "证监会", "央行", "发改委", "工信部", "财政部",
    "交易所", "地方政府", "媒体转载", "行业协会", "未知来源",
]

PolicyLevel = Literal[
    "国家级", "部委级", "地方级", "交易所规则", "行业协会倡议", "未明确",
]

PolicyType = Literal[
    "宏观流动性", "财政刺激", "产业扶持", "监管收紧",
    "资本市场制度", "行业准入", "税收调整", "土地/房地产",
    "科技/创新", "数据/安全", "对外开放", "其他",
]

MarketReaction = Literal["未反应", "部分反应", "充分反应", "过度反应"]
TimeHorizon = Literal["当天", "1-5个交易日", "1-3个月", "长期产业趋势"]
SourceReliability = Literal["官方原文", "官方摘要", "媒体报道", "转载", "传言", "无法验证"]

Direction = Literal["利好", "利空", "中性", "结构性影响"]


@dataclass
class AffectedSector:
    """一个受益或受损方向的具体描述."""
    sector: str                       # 板块/行业名称
    direction: Direction              # 方向
    stocks: list[str] = field(default_factory=list)  # 代表性标的（可选）
    reason: str = ""                  # 影响逻辑

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyAnalysisReport:
    """
    Complete policy analysis — the structured output.

    Rules:
    - 政策交易价值评分 < 60 → 不得进入交易候选
    - 来源不可靠或信息不完整 → need_verify=True, 不可交易
    """

    # ── Identity ──
    policy_title: str = ""
    source_url: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Step 1-2: Source & level ──
    source: SourceType = "未知来源"
    source_reliability: SourceReliability = "无法验证"
    policy_level: PolicyLevel = "未明确"

    # ── Step 3: Type ──
    policy_type: PolicyType = "其他"

    # ── Step 4: Impact direction ──
    overall_direction: Direction = "中性"
    beneficiaries: list[dict[str, Any]] = field(default_factory=list)
    harmed: list[dict[str, Any]] = field(default_factory=list)

    # ── Step 5: Timeline ──
    time_horizon: TimeHorizon = "1-5个交易日"
    # ── Step 6: Market reaction ──
    market_reaction: MarketReaction = "未反应"
    # ── Step 7: Score ──
    trading_score: float = 0.0          # 0-100
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)

    # ── Step 8: Verification ──
    need_verify: bool = True
    verify_reason: str = ""
    is_tradeable: bool = False           # False if score < 60 or need_verify

    # ── Narrative ──
    analysis_path: list[str] = field(default_factory=list)
    summary: str = ""
    risk_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_title": self.policy_title,
            "source_url": self.source_url,
            "generated_at": self.generated_at,
            "source": self.source,
            "source_reliability": self.source_reliability,
            "policy_level": self.policy_level,
            "policy_type": self.policy_type,
            "overall_direction": self.overall_direction,
            "beneficiaries": self.beneficiaries,
            "harmed": self.harmed,
            "time_horizon": self.time_horizon,
            "market_reaction": self.market_reaction,
            "trading_score": round(self.trading_score, 1),
            "score_breakdown": self.score_breakdown,
            "need_verify": self.need_verify,
            "verify_reason": self.verify_reason,
            "is_tradeable": self.is_tradeable,
            "analysis_path": self.analysis_path,
            "summary": self.summary,
            "risk_note": self.risk_note,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 政策分析仅用于研究参考，不构成投资建议。"
            "政策传导路径存在不确定性，实际影响可能偏离分析结论。"
            "评分 < 60 不得交易，来源不可靠或信息不完整不得交易。"
        )
