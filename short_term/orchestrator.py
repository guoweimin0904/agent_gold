"""Short-term auxiliary orchestrator — runs commodity + sentiment scans.

This does NOT modify the main scoring system.
Outputs a standalone ShortTermAuxReport for human reference only.
"""

import logging
from pathlib import Path
from typing import Any

from short_term.commodity import get_commodity_prices
from short_term.schemas import ShortTermAuxReport
from short_term.sentiment_flow import detect_short_term_sentiment

logger = logging.getLogger("short_term.orchestrator")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "short_term_aux_report.json"


def run_short_term_aux(
    stock_code: str = "",
    stock_name: str = "",
    sector: str = "",
    main_composite_score: float = 0.0,
    klines: list[dict[str, Any]] | None = None,
    heat_score: float = 50.0,
    limit_up_5d: int = 0,
    price_change_5d_pct: float = 0.0,
    force_commodities: list[str] | None = None,
) -> ShortTermAuxReport:
    """
    运行短线辅助扫描 — 不参与主评分，仅输出辅助报告。

    包含:
    - 大宗商品现货价格追踪（关联股票自动匹配）
    - 短线游资/题材情绪检测
    """
    logger.info("短线辅助扫描: %s(%s)", stock_name, stock_code)

    # ── 1. 大宗商品 ──
    commodity_signals = get_commodity_prices(
        stock_name=stock_name,
        commodities=force_commodities,
    )

    # ── 2. 短线情绪 ──
    sentiment_signals = detect_short_term_sentiment(
        stock_name=stock_name,
        sector=sector,
        klines=klines,
        heat_score=heat_score,
        limit_up_5d=limit_up_5d,
        price_change_5d_pct=price_change_5d_pct,
    )

    # ── 3. 综合判定 ──
    verdict, confidence = _compose_verdict(
        commodity_signals, sentiment_signals, main_composite_score
    )

    report = ShortTermAuxReport(
        symbol=stock_code,
        stock_name=stock_name,
        main_composite_score=main_composite_score,
        commodity_signals=[s.to_dict() for s in commodity_signals],
        sentiment_signals=[s.to_dict() for s in sentiment_signals],
        short_term_verdict=verdict,
        short_term_confidence=confidence,
        suggestion=_build_suggestion(verdict, main_composite_score),
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report.to_json())
    logger.info("短线辅助报告已保存: %s", REPORT_PATH)

    _print(report)
    return report


def _compose_verdict(
    commodity_signals: list,
    sentiment_signals: list,
    main_score: float,
) -> tuple[str, str]:
    """综合判定短线方向。"""
    has_commodity_up = any(
        getattr(s, "price_change_1w_pct", 0) > 2 for s in commodity_signals
    )
    has_sentiment_opp = any(
        getattr(s, "signal_type", "") == "opportunity" for s in sentiment_signals
    )
    has_warning = any(
        getattr(s, "signal_type", "") == "warning" for s in sentiment_signals
    )

    if has_warning:
        return "短线风险信号，建议观望", "高"
    if has_commodity_up and has_sentiment_opp:
        return "商品涨价+游资活跃，短线存在博弈机会但风险高", "中"
    if has_commodity_up:
        return "大宗商品上涨，但缺少短线资金确认", "低"
    if has_sentiment_opp:
        return "短线情绪活跃，但缺少基本面/商品支撑", "低"
    return "无明确短线信号", "低"


def _build_suggestion(verdict: str, main_score: float) -> str:
    """生成建议文案。"""
    if main_score >= 70:
        return "主评分系统已推荐，短线辅助信号可作为入场时机参考"
    if "博弈" in verdict:
        return (
            "⚠️ 短线存在博弈机会，但主评分<70不满足自动交易条件。"
            "如需参与，请严格设止损、轻仓、不过夜。"
        )
    return "建议以主评分系统为主，短线辅助仅作为人工参考"


def _print(report: ShortTermAuxReport) -> None:
    print(f"\n{'='*55}")
    print(f"  📡 短线辅助参考（不参与评分，仅人工参考）")
    print(f"  {report.stock_name}({report.symbol}) 主评分: {report.main_composite_score}")
    print(f"{'='*55}")
    print(f"  综合判定: {report.short_term_verdict}")
    print(f"  可信度: {report.short_term_confidence}")
    print()
    if report.commodity_signals:
        print(f"  📦 大宗商品:")
        for c in report.commodity_signals:
            if c.get("data_available"):
                print(f"    {c['commodity']}: {c['spot_price']}  "
                      f"1周{c['price_change_1w_pct']:+.1f}% 1月{c['price_change_1m_pct']:+.1f}%  "
                      f"[{c['trend_direction']}]")
            else:
                print(f"    {c['commodity']}: {c['summary']}")
    if report.sentiment_signals:
        print(f"  🔥 短线情绪:")
        for s in report.sentiment_signals:
            print(f"    [{s['signal_type']}] {s['topic']}: {s['summary']}")
    print(f"\n  💡 {report.suggestion}")
    print(f"{'='*55}")
