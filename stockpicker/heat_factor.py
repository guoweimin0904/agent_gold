"""短期情绪热度辅助因子模块（方案A）

独立辅助打分，不参与综合交易评分，仅作为参考标签。

指标：
- 近3日换手率（相对20日均值）
- 成交额增幅（近3日 vs 近20日）
- 短线涨停次数（近5日是否触及涨停）
- 股吧/社交媒体热度（关键词提及频率）

输出标签：
- 高热度回避：热度极高但基本面/技术面差
- 高热度中性：热度高但评分普通
- 热度趋势共振：热度与评分方向一致
"""

import logging
from dataclasses import dataclass, asdict
from typing import Any, Literal

logger = logging.getLogger("stockpicker.heat")

HeatLabel = Literal["高热度回避", "高热度中性", "热度趋势共振", "热度正常"]


@dataclass
class HeatFactorReport:
    """短期情绪热度辅助报告（不参与评分，仅供参考）"""
    # 原始指标
    turnover_ratio_3d: float = 0.0         # 近3日平均换手率
    turnover_ratio_20d: float = 0.0        # 近20日平均换手率
    turnover_ratio_change: float = 0.0     # 换手率变化倍数
    amount_change_ratio: float = 0.0       # 成交额增幅倍数（近3日/近20日）
    price_change_5d_pct: float = 0.0       # 5日涨幅
    limit_up_count_5d: int = 0             # 5日涨停次数
    limit_down_count_5d: int = 0           # 5日跌停次数

    # 辅助标签（由compute输出）
    heat_label: HeatLabel = "热度正常"
    heat_score: float = 50.0               # 热度评分 0-100（仅供参考）
    composite_score: float = 50.0          # 传入的综合评分
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_heat_factor(
    klines: list[dict[str, Any]] | None = None,
    composite_score: float = 50.0,
    limit_up_data: list[dict[str, Any]] | None = None,
) -> HeatFactorReport:
    """
    计算短期情绪热度辅助因子。

    Parameters
    ----------
    klines : list[dict]
        日K线数据，需含 close, volume, high, low, turnover(可选)
    composite_score : float
        主评分系统的综合评分（用于判断背离）
    limit_up_data : list[dict], optional
        涨停数据（预留接口）

    Returns
    -------
    HeatFactorReport
    """
    if not klines or len(klines) < 25:
        return HeatFactorReport(
            heat_label="热度正常", heat_score=50.0, composite_score=composite_score,
            summary="数据不足，无法计算热度因子"
        )

    records = klines[-25:]  # 最近25根K线
    closes = [float(k["close"]) for k in records]
    volumes = [float(k.get("volume", 0)) for k in records]
    highs = [float(k["high"]) for k in records]
    lows = [float(k["low"]) for k in records]

    recent_5 = records[-5:] if len(records) >= 5 else records
    recent_3 = records[-3:] if len(records) >= 3 else records

    # ── 换手率分析 ──
    vol_3d_avg = sum(v for v in [float(k.get("volume", 0)) for k in recent_3]) / len(recent_3)
    vol_20d_avg = sum(volumes) / len(volumes)
    turnover_change = vol_3d_avg / vol_20d_avg if vol_20d_avg > 0 else 1.0

    # ── 成交额增幅 ──
    amount_3d_avg = sum(float(k.get("amount", k.get("volume", 0))) for k in recent_3) / len(recent_3)
    amount_20d_avg = sum(float(k.get("amount", k.get("volume", 0))) for k in records) / len(records)
    amount_change = amount_3d_avg / amount_20d_avg if amount_20d_avg > 0 else 1.0

    # ── 短线涨幅 ──
    price_5d_pct = (closes[-1] - closes[-5]) / closes[-5] * 100 if len(closes) >= 5 else 0
    price_3d_pct = (closes[-1] - closes[-3]) / closes[-3] * 100 if len(closes) >= 3 else 0

    # ── 涨停/跌停次数 ──
    limit_up = 0
    limit_down = 0
    for k in recent_5:
        chg = (float(k["close"]) - float(k["open"])) / float(k["open"]) * 100
        if chg >= 9.5:
            limit_up += 1
        elif chg <= -9.5:
            limit_down += 1

    # ── 热度评分（纯辅助） ──
    heat = 50.0
    reasons: list[str] = []

    # 换手率贡献
    if turnover_change > 3:
        heat += 20
        reasons.append(f"换手率爆增{turnover_change:.1f}x")
    elif turnover_change > 2:
        heat += 12
        reasons.append(f"换手率显著放量{turnover_change:.1f}x")
    elif turnover_change > 1.3:
        heat += 5
        reasons.append(f"换手率温和放量{turnover_change:.1f}x")
    elif turnover_change < 0.5:
        heat -= 10
        reasons.append(f"换手率萎缩{turnover_change:.1f}x")

    # 成交额贡献
    if amount_change > 2:
        heat += 15
    elif amount_change > 1.5:
        heat += 8

    # 涨停贡献
    if limit_up >= 2:
        heat += 20
        reasons.append(f"近5日{limit_up}次涨停")
    elif limit_up == 1:
        heat += 10
        reasons.append("近5日1次涨停")

    # 短线涨幅贡献
    if price_5d_pct > 15:
        heat += 15
        reasons.append(f"5日暴涨{price_5d_pct:.1f}%")
    elif price_5d_pct > 8:
        heat += 8
        reasons.append(f"5日大涨{price_5d_pct:.1f}%")
    elif price_5d_pct < -10:
        heat -= 10
        reasons.append(f"5日暴跌{price_5d_pct:.1f}%")

    heat = max(5, min(98, heat))

    # ── 标签判定（核心：热度和主评分背离检测） ──
    if heat >= 70 and composite_score < 55:
        heat_label: HeatLabel = "高热度回避"
        summary = (
            f"⚠️ 短期热度{heat:.0f}分但综合评分仅{composite_score:.1f}分，存在明显背离。"
            f"短线情绪过热但基本面/技术面不支持，风险较高。"
        )
    elif heat >= 70 and composite_score >= 70:
        heat_label = "热度趋势共振"
        summary = (
            f"🔥 短期热度{heat:.0f}分与综合评分{composite_score:.1f}分共振！"
            f"短线情绪面和基本面方向一致，可关注趋势延续。"
        )
    elif heat >= 60 and composite_score >= 55:
        heat_label = "热度趋势共振"
        summary = f"热度{heat:.0f}分与评分{composite_score:.1f}分基本一致，方向趋同。"
    elif heat >= 60:
        heat_label = "高热度中性"
        summary = f"热度{heat:.0f}分中等偏高，但评分{composite_score:.1f}分一般，建议结合其他维度判断。"
    else:
        heat_label = "热度正常"
        summary = f"热度{heat:.0f}分正常，无异常情绪信号。"

    return HeatFactorReport(
        turnover_ratio_3d=round(turnover_change, 2),
        turnover_ratio_20d=round(vol_20d_avg, 0),
        turnover_ratio_change=round(turnover_change, 2),
        amount_change_ratio=round(amount_change, 2),
        price_change_5d_pct=round(price_5d_pct, 2),
        limit_up_count_5d=limit_up,
        limit_down_count_5d=limit_down,
        heat_label=heat_label,
        heat_score=round(heat, 1),
        composite_score=round(composite_score, 1),
        summary=summary,
    )
