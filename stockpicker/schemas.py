"""Stock picker schemas — the unified output for A-share individual stock analysis.

Combines:
- 基本面/估值评分 (value_score)
- 技术面评分 (technical_score)
- 板块政策联动 (policy_linkage)
- 资金面评分 (fund_score)
- 综合鉴股结论
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

StockRating = Literal["强烈推荐", "推荐", "关注", "回避", "中性"]
MarketType = Literal["主板", "创业板", "科创板", "北交所"]
Sector = Literal[
    "半导体", "人工智能", "新能源", "光伏", "风电", "储能",
    "汽车", "消费电子", "医药", "金融", "地产", "基建",
    "军工", "消费", "农业", "化工", "有色", "煤炭",
    "通信", "计算机", "传媒", "其他",
]


@dataclass
class FundamentalScore:
    """基本面/估值评分维度."""
    pe_score: float = 50.0          # 市盈率维度 0-100
    pb_score: float = 50.0          # 市净率维度
    roe_score: float = 50.0         # ROE维度
    growth_score: float = 50.0      # 成长性维度
    debt_score: float = 50.0        # 负债维度
    dividend_score: float = 50.0    # 分红维度
    total: float = 50.0
    summary: str = ""


@dataclass
class TechnicalScore:
    """技术面评分维度."""
    trend_score: float = 50.0       # 趋势
    momentum_score: float = 50.0    # 动量
    volume_score: float = 50.0      # 量能
    support_resist: float = 50.0    # 支撑阻力
    total: float = 50.0
    summary: str = ""


@dataclass
class PolicyLinkage:
    """板块-政策联动分析."""
    sector: Sector = "其他"
    sector_strength: float = 50.0   # 板块强度 0-100
    policy_alignment: float = 50.0  # 政策契合度 0-100
    active_policy: str = ""          # 关联的活跃政策
    policy_direction: str = "中性"
    benefit_level: str = "无"       # 受益程度: 直接受益/间接受益/无


@dataclass
class StockAnalysisReport:
    """完整个股鉴股报告."""
    # ── Identity ──
    stock_code: str = ""             # 6位代码
    stock_name: str = ""
    market: MarketType = "主板"
    sector: Sector = "其他"
    current_price: float = 0.0
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── 多维度评分 ──
    fundamental: FundamentalScore = field(default_factory=FundamentalScore)
    technical: TechnicalScore = field(default_factory=TechnicalScore)
    fund_flow_score: float = 50.0   # 资金流向 0-100
    policy_linkage: PolicyLinkage = field(default_factory=PolicyLinkage)
    news_sentiment: float = 50.0    # 新闻舆情 0-100

    # ── 综合 ──
    composite_score: float = 50.0   # 综合评分 0-100
    rating: StockRating = "中性"
    confidence: float = 0.5
    reason_summary: list[str] = field(default_factory=list)

    # ── 方案A: 短期情绪热度辅助因子（不参与评分） ──
    heat_factor: dict[str, Any] = field(default_factory=dict)

    # ── 方案B: 短期评分明细 ──
    short_term_momentum_bonus: float = 0.0
    short_term_event_score: float = 50.0

    # ── 方案C: 增强数据（龙虎榜、融资融券） ──
    dragon_tiger_data: list[dict[str, Any]] = field(default_factory=list)
    margin_data: dict[str, Any] = field(default_factory=dict)

    # ── 交易参考 ──
    support_level: str = ""
    resistance_level: str = ""
    risk_note: str = ""
    is_tradeable: bool = False      # composite >= 70 可交易

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "market": self.market,
            "sector": self.sector,
            "current_price": self.current_price,
            "generated_at": self.generated_at,
            "fundamental": asdict(self.fundamental),
            "technical": asdict(self.technical),
            "fund_flow_score": round(self.fund_flow_score, 1),
            "policy_linkage": asdict(self.policy_linkage),
            "news_sentiment": round(self.news_sentiment, 1),
            "composite_score": round(self.composite_score, 1),
            "rating": self.rating,
            "confidence": round(self.confidence, 2),
            "short_term_momentum_bonus": round(self.short_term_momentum_bonus, 1),
            "short_term_event_score": round(self.short_term_event_score, 1),
            "heat_factor": self.heat_factor,
            "dragon_tiger_data": self.dragon_tiger_data,
            "margin_data": self.margin_data,
            "reason_summary": self.reason_summary,
            "support_level": self.support_level,
            "resistance_level": self.resistance_level,
            "risk_note": self.risk_note,
            "is_tradeable": self.is_tradeable,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 本分析仅供研究参考，不构成任何投资建议。"
            "A股市场存在政策风险、流动性风险、退市风险。"
            "综合评分 ≥ 70 方可进入交易候选，且需配合风控审查。"
        )
