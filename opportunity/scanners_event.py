"""Scanner: 交易所上币 (listing) + 黑天鹅 (blackswan) + 情绪极端 (sentiment extreme)."""
from __future__ import annotations

import logging
from typing import Any

from opportunity.schemas import OpportunitySignal, ScannerMetadata

logger = logging.getLogger("opportunity.scanners.event")


def scan_listing(
    symbol: str,
    exchange_announcements: list[dict[str, Any]] | None = None,
    price_change_24h_pct: float = 0.0,
    volume_24h: float = 0.0,
) -> OpportunitySignal:
    """
    Scanner: 交易所上币公告 → 捕捉短期事件。

    event_score: 上币事件本身的价值（0-100）
    already_pumped: 市场是否已提前拉升（0.0-1.0）
    trade_window: 最佳交易窗口
    """
    if not exchange_announcements:
        return OpportunitySignal(
            signal_type="listing", symbol=symbol, priority="info",
            score=50, confidence=0.0, event_score=50,
            already_pumped=0.0, trade_window="未知",
            summary="无交易所上币数据",
            scanner_meta=ScannerMetadata(scanner="listing", data_available=False, data_missing=True),
        )

    # Find matching announcement
    matching = [a for a in exchange_announcements if symbol.upper() in str(a).upper()]
    if not matching:
        return OpportunitySignal(
            signal_type="listing", symbol=symbol, priority="info",
            score=30, confidence=0.0, event_score=30,
            already_pumped=0.0, trade_window="未知",
            summary=f"未找到{symbol}的相关上币公告",
            scanner_meta=ScannerMetadata(scanner="listing"),
        )

    # Score based on exchange tier
    ann_text = str(matching[0])
    if any(e in ann_text for e in ["Binance", "Coinbase", "Upbit"]):
        base_score = 85
        reason = "头部交易所上币"
    elif any(e in ann_text for e in ["OKX", "Bybit", "Kucoin", "Gate"]):
        base_score = 70
        reason = "主流交易所上币"
    else:
        base_score = 55
        reason = "小型交易所上币"

    # Adjust for pre-pump
    pump = max(0, min(1.0, abs(price_change_24h_pct) / 30))
    already_pumped = pump
    event_score = base_score * (1 - pump * 0.5)  # pre-pump halves the event value

    # Trade window
    if "立即" in ann_text or "即将" in ann_text:
        trade_window = "1-3h内"
    elif "今日" in ann_text:
        trade_window = "4-12h"
    else:
        trade_window = "12-48h"

    priority = "high" if event_score >= 70 and already_pumped < 0.4 else "medium"
    return OpportunitySignal(
        signal_type="listing", symbol=symbol, priority=priority,
        score=round(event_score, 1), confidence=round(1 - already_pumped, 2),
        event_score=round(event_score, 1),
        already_pumped=round(already_pumped, 2),
        trade_window=trade_window,
        summary=f"{reason} | event_score={event_score:.0f} | pre-pump={already_pumped:.0%}",
        scanner_meta=ScannerMetadata(scanner="listing"),
    )


def scan_blackswan(
    symbol: str,
    news_report: dict[str, Any] | None = None,
    risk_status: dict[str, Any] | None = None,
    price_drop_24h_pct: float = 0.0,
) -> OpportunitySignal:
    """
    Scanner: 黑天鹅事件 → 避免暴跌风险。

    risk_level: low/medium/high/critical
    panic_probability: 0.0-1.0
    risk_pause: True if S-level event or panic_probability > 0.7
    """
    risk_level = "low"
    panic_prob = 0.0
    risk_pause = False
    reasons: list[str] = []

    # News-based panic detection
    if news_report and news_report.get("reports"):
        for r in news_report["reports"]:
            il = r.get("impact_level", "C")
            truth = r.get("truth_status", "")
            title = r.get("title", "")
            rp = r.get("risk_pause", False)

            if il == "S" or rp:
                panic_prob = max(panic_prob, 0.8)
                risk_pause = True
                reasons.append(f"S级事件: {title[:40]}")
            elif il == "A" and truth in ("rumour", "unverified"):
                panic_prob = max(panic_prob, 0.5)
                reasons.append(f"A级未验证事件: {title[:40]}")

    # Risk status
    if risk_status:
        if risk_status.get("kill_switch_active"):
            panic_prob = max(panic_prob, 0.9)
            risk_pause = True
            reasons.append("杀开关已激活")
        if risk_status.get("s_event_active"):
            panic_prob = max(panic_prob, 0.85)
            risk_pause = True
            reasons.append("S级事件风险暂停")
        mdd = risk_status.get("market_drawdown_pct", 0)
        if mdd > 15:
            panic_prob = max(panic_prob, 0.6)
            reasons.append(f"市场回撤{mdd:.1f}%")

    # Price drop
    if price_drop_24h_pct < -10:
        panic_prob = max(panic_prob, 0.7)
        reasons.append(f"24h暴跌{price_drop_24h_pct:.1f}%")
    elif price_drop_24h_pct < -5:
        panic_prob = max(panic_prob, 0.35)
        reasons.append(f"24h下跌{price_drop_24h_pct:.1f}%")

    panic_prob = min(1.0, panic_prob)
    if panic_prob >= 0.7:
        risk_level = "critical"
    elif panic_prob >= 0.4:
        risk_level = "high"
    elif panic_prob >= 0.2:
        risk_level = "medium"

    score = (1 - panic_prob) * 50  # lower score = higher risk
    priority = "critical" if risk_pause else ("high" if risk_level in ("high", "critical") else "medium")

    return OpportunitySignal(
        signal_type="blackswan", symbol=symbol, priority=priority,
        score=round(score, 1), confidence=round(1 - panic_prob, 2),
        risk_level=risk_level, panic_probability=round(panic_prob, 2),
        risk_pause=risk_pause,
        summary="; ".join(reasons) if reasons else "未检测到黑天鹅风险",
        scanner_meta=ScannerMetadata(scanner="blackswan"),
    )


def scan_extreme_sentiment(
    symbol: str,
    sentiment_score: float = 50.0,
    rsi: float = 50.0,
    price_change_24h_pct: float = 0.0,
    price_change_7d_pct: float = 0.0,
) -> OpportunitySignal:
    """
    Scanner: 情绪极端 → 寻找反向机会。

    sentiment_score: 0-100 (aggregate sentiment)
    is_extreme: True if panic or fomo
    contrarian_signal: True for extreme → suggests reversal
    """
    is_extreme = False
    contrarian = False
    direction = "neutral"

    # Sentiment extreme (from news/social)
    if sentiment_score <= 15:
        is_extreme = True
        contrarian = True
        direction = "extreme_fear → potential_reversal"
    elif sentiment_score >= 85:
        is_extreme = True
        contrarian = True
        direction = "extreme_greed → potential_reversal"

    # RSI extreme
    if rsi <= 25:
        is_extreme = True
        contrarian = True
        direction = "RSI超卖 → 可能反弹"
    elif rsi >= 78:
        is_extreme = True
        contrarian = True
        direction = "RSI超买 → 可能回调"

    # Price extreme
    if price_change_7d_pct > 40:
        is_extreme = True
        direction = "7d暴涨 → 注意FOMO"
    elif price_change_7d_pct < -30:
        is_extreme = True
        contrarian = True
        direction = "7d暴跌 → 可能超跌反弹"

    score = sentiment_score  # base on sentiment
    if is_extreme and contrarian:
        # Extreme + contrarian = opportunity
        score = 80 - abs(sentiment_score - 50) * 0.5
        if sentiment_score < 30:
            score = 70 + (30 - sentiment_score)  # fear → buy opp
        elif sentiment_score > 70:
            score = 70 - (sentiment_score - 70)  # greed → sell opp

    priority = "high" if is_extreme and contrarian else ("medium" if is_extreme else "low")

    return OpportunitySignal(
        signal_type="extreme_sentiment", symbol=symbol, priority=priority,
        score=round(max(10, min(90, score)), 1),
        confidence=round(0.6 if is_extreme else 0.3, 2),
        sentiment_score=round(sentiment_score, 1),
        is_extreme=is_extreme, contrarian_signal=contrarian,
        summary=f"{direction} | sentiment={sentiment_score:.0f} | RSI={rsi:.0f}",
        scanner_meta=ScannerMetadata(scanner="extreme_sentiment"),
    )
