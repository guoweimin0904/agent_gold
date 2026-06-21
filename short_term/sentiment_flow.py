"""短线游资/题材情绪因子 — 短线辅助参考，不参与主评分。

数据来源:
1. AKShare 板块涨停家数 (board_limited_up_em)
2. 龙虎榜营业部排名
3. K线量价异常检测 (换手率爆增+涨停)
"""

import logging
from typing import Any

import akshare as ak

from short_term.schemas import SentimentFlowSignal

logger = logging.getLogger("short_term.sentiment")


def detect_short_term_sentiment(
    stock_name: str = "",
    sector: str = "",
    klines: list[dict[str, Any]] | None = None,
    heat_score: float = 50.0,
    limit_up_5d: int = 0,
    price_change_5d_pct: float = 0.0,
) -> list[SentimentFlowSignal]:
    """
    检测短线游资/题材情绪信号。

    输出信号类型:
    - opportunity: 板块有游资活跃迹象
    - warning: 板块过热或退潮
    - info: 正常
    - neutral: 无信号
    """
    signals: list[SentimentFlowSignal] = []

    # ── 1. 检查板块涨停情况 ──
    if sector:
        try:
            df = ak.stock_zt_pool_em(date="20260618")
            if df is not None and not df.empty:
                board_count = len(df[df["板块"] == sector]) if "板块" in df.columns else 0
                if board_count > 0:
                    signals.append(SentimentFlowSignal(
                        topic=f"{sector}板块",
                        heat_score=min(80, 50 + board_count * 5),
                        capital_flow_est="游资活跃" if board_count >= 3 else "零星参与",
                        limit_up_count=board_count,
                        leader_stock=str(df.iloc[0].get("名称", "")) if not df.empty else "",
                        signal_type="opportunity" if board_count >= 3 else "info",
                        summary=f"{sector}板块今日{board_count}只涨停，短线活跃",
                    ))
        except Exception as e:
            logger.warning("涨停数据获取失败: %s (可忽略)", e)

    # ── 2. 个股异动检测 ──
    if klines and len(klines) >= 5 and stock_name:
        # 换手率异动
        recent_vols = [float(k.get("volume", 0)) for k in klines[-3:]]
        older_vols = [float(k.get("volume", 0)) for k in klines[-10:-3]]
        if older_vols and sum(recent_vols) / 3 > sum(older_vols) / 7 * 2.5:
            signals.append(SentimentFlowSignal(
                topic=f"{stock_name}异动",
                heat_score=round(min(85, 50 + heat_score * 0.3), 1),
                capital_flow_est="放量异动，注意游资",
                limit_up_count=limit_up_5d,
                signal_type="opportunity" if limit_up_5d >= 1 else "info",
                summary=f"{stock_name}近3日换手率爆增，有短线资金介入迹象",
            ))

        # 涨停异动
        if limit_up_5d >= 1:
            signals.append(SentimentFlowSignal(
                topic=f"{stock_name}涨停",
                heat_score=round(min(90, 50 + limit_up_5d * 15), 1),
                capital_flow_est="涨停板游资",
                limit_up_count=limit_up_5d,
                signal_type="opportunity",
                summary=f"{stock_name}近5日{limit_up_5d}次涨停，短线情绪活跃",
            ))

        # 暴跌异动
        if price_change_5d_pct < -10:
            signals.append(SentimentFlowSignal(
                topic=f"{stock_name}急跌",
                heat_score=30,
                capital_flow_est="资金出逃",
                limit_up_count=0,
                signal_type="warning",
                summary=f"{stock_name}近5日暴跌{price_change_5d_pct:.1f}%，注意恐慌踩踏",
            ))

    if not signals:
        signals.append(SentimentFlowSignal(
            topic=stock_name or sector or "短线",
            heat_score=50,
            signal_type="neutral",
            summary="当前无明确短线游资信号",
        ))

    return signals
