"""Short-term auxiliary report schema — not part of main scoring."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

SignalType = Literal["warning", "info", "opportunity", "neutral"]


@dataclass
class CommoditySpotSignal:
    """大宗商品现货价格信号（辅助参考，不参与评分）"""
    commodity: str = ""                    # 商品名称，如 "钨精矿"
    spot_price: float = 0.0               # 现货价格
    price_change_1w_pct: float = 0.0      # 近1周涨跌幅
    price_change_1m_pct: float = 0.0      # 近1月涨跌幅
    price_change_3m_pct: float = 0.0      # 近3月涨跌幅
    trend_direction: str = "平稳"          # 上涨/下跌/平稳
    signal_type: SignalType = "neutral"
    summary: str = ""
    data_source: str = ""                 # 数据来源
    data_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SentimentFlowSignal:
    """短线游资/题材情绪信号（辅助参考，不参与评分）"""
    topic: str = ""                        # 题材名称，如 "钨涨价"
    heat_score: float = 50.0               # 热度 0-100
    capital_flow_est: str = "中性"          # 资金流向估计
    limit_up_count: int = 0                # 板块内涨停家数
    leader_stock: str = ""                 # 龙头股
    signal_type: SignalType = "neutral"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ShortTermAuxReport:
    """
    短线辅助报告 — 不参与主评分系统，仅作为人工参考弹窗。

    包含:
    - 大宗商品现货价格追踪
    - 短线游资/题材情绪
    """
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    symbol: str = ""
    stock_name: str = ""
    main_composite_score: float = 0.0      # 主评分，仅供参考

    # 辅助信号
    commodity_signals: list[dict[str, Any]] = field(default_factory=list)
    sentiment_signals: list[dict[str, Any]] = field(default_factory=list)

    # 综合短线判断
    short_term_verdict: str = "无明确短线信号"
    short_term_confidence: str = "低"       # 高/中/低
    suggestion: str = "建议以主评分系统为主，短线辅助仅作为人工参考"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
