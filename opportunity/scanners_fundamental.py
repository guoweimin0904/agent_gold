"""Scanner: 政策驱动 (policy) + 业绩/公告 (earnings)."""
from __future__ import annotations

import logging
from typing import Any

from opportunity.schemas import OpportunitySignal, ScannerMetadata

logger = logging.getLogger("opportunity.scanners.fundamental")


def scan_policy(
    symbol: str,
    policy_report: dict[str, Any] | None = None,
) -> OpportunitySignal:
    """
    Scanner: 政策驱动 → 提前识别板块机会。

    policy_score: 政策交易价值评分 0-100
    benefit_sector: 受益板块
    risk_note: 政策风险提示
    """
    if not policy_report:
        return OpportunitySignal(
            signal_type="policy", symbol=symbol, priority="info",
            score=50, confidence=0.0, policy_score=50,
            benefit_sector="", risk_note="无政策数据",
            summary="无政策分析数据",
            scanner_meta=ScannerMetadata(scanner="policy", data_missing=True),
        )

    trading_score = policy_report.get("trading_score", 0)
    is_tradeable = policy_report.get("is_tradeable", False)
    direction = policy_report.get("overall_direction", "中性")
    source = policy_report.get("source", "未知")
    level = policy_report.get("policy_level", "未明确")
    ptype = policy_report.get("policy_type", "其他")
    need_verify = policy_report.get("need_verify", True)
    beneficiaries = policy_report.get("beneficiaries", [])
    risk_note = policy_report.get("risk_note", "")
    summary = policy_report.get("summary", "")

    # Determine if our symbol benefits
    benefit_sector = ""
    for b in beneficiaries:
        sector = b.get("sector", "")
        if symbol.upper() in sector.upper() or not benefit_sector:
            benefit_sector = sector

    priority = "high" if is_tradeable and trading_score >= 70 else \
               "medium" if is_tradeable else "info"

    return OpportunitySignal(
        signal_type="policy", symbol=symbol, priority=priority,
        score=round(trading_score, 1),
        confidence=round(trading_score / 100, 2) if is_tradeable else 0.2,
        policy_score=round(trading_score, 1),
        benefit_sector=benefit_sector,
        risk_note=risk_note,
        summary=f"{direction} | {source}({level}) | {ptype} | {summary[:40]}",
        scanner_meta=ScannerMetadata(scanner="policy"),
    )


def scan_earnings(
    symbol: str,
    earnings_data: list[dict[str, Any]] | None = None,
    corporate_events: list[dict[str, Any]] | None = None,
) -> OpportunitySignal:
    """
    Scanner: 业绩/公告 → 捕捉基本面变化。

    earnings_surprise: 业绩超预期程度 0.0-1.0
    risk_flag: 是否有诉讼/减持/处罚等负面事件
    """
    score = 50.0
    earnings_surprise = 0.0
    risk_flag = False
    reasons: list[str] = []

    # Earnings data
    if earnings_data:
        for e in earnings_data:
            if e.get("symbol", "").upper() != symbol.upper():
                continue
            surprise = e.get("surprise_pct", 0)
            actual = e.get("actual", 0)
            estimate = e.get("estimate", 0)

            if surprise > 20:
                earnings_surprise = min(1.0, surprise / 50)
                score += 20
                reasons.append(f"业绩超预期{surprise:.0f}%")
            elif surprise > 5:
                earnings_surprise = 0.5
                score += 8
                reasons.append(f"业绩略超预期{surprise:.0f}%")
            elif surprise < -20:
                earnings_surprise = 0.0
                score -= 15
                risk_flag = True
                reasons.append(f"业绩不及预期{surprise:.0f}%")
            break

    # Corporate events
    if corporate_events:
        for ev in corporate_events:
            if ev.get("symbol", "").upper() != symbol.upper():
                continue
            etype = ev.get("type", "")
            detail = ev.get("detail", "")

            if etype in ("buyback", "回购"):
                score += 10
                reasons.append(f"回购公告")
            elif etype in ("insider_sell", "减持"):
                score -= 10
                risk_flag = True
                reasons.append(f"股东减持")
            elif etype in ("lawsuit", "诉讼"):
                score -= 20
                risk_flag = True
                reasons.append(f"诉讼/处罚")
            elif etype in ("dividend", "分红"):
                score += 5
                reasons.append(f"分红公告")
            elif etype in ("profit_warning", "业绩预告"):
                direction = detail.get("direction", "positive")
                if direction == "positive":
                    score += 12
                    reasons.append(f"业绩预增")
                else:
                    score -= 12
                    risk_flag = True
                    reasons.append("业绩预亏")

    score = max(10, min(95, score))
    priority = "high" if score >= 70 and not risk_flag else \
               "medium" if score >= 50 else "low"

    return OpportunitySignal(
        signal_type="earnings", symbol=symbol, priority=priority,
        score=round(score, 1),
        confidence=round(0.5 + earnings_surprise * 0.4, 2),
        earnings_surprise=round(earnings_surprise, 2),
        risk_flag=risk_flag,
        summary="; ".join(reasons) if reasons else "无近期业绩/公告事件",
        scanner_meta=ScannerMetadata(scanner="earnings"),
    )
