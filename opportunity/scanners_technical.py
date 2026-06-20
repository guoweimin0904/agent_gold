"""Scanner: 突破行情 (breakout) + 资金驱动 (fund_flow)."""

import logging
from typing import Any

from opportunity.schemas import OpportunitySignal, ScannerMetadata

logger = logging.getLogger("opportunity.scanners.technical")


def scan_breakout(
    symbol: str,
    klines: list[dict[str, Any]] | None = None,
    indicators: dict[str, Any] | None = None,
) -> OpportunitySignal:
    """
    Scanner: 突破行情 → 顺势交易。

    kline_score: K线形态评分 0-100
    breakout: 是否突破关键位
    volume_confirmed: 成交量是否确认
    """
    if not klines or len(klines) < 30:
        return OpportunitySignal(
            signal_type="breakout", symbol=symbol, priority="info",
            score=50, confidence=0.0, kline_score=50,
            breakout=False, volume_confirmed=False,
            summary="K线数据不足",
            scanner_meta=ScannerMetadata(scanner="breakout", data_missing=True),
        )

    closes = [float(k["close"]) for k in klines[-30:]]
    highs = [float(k["high"]) for k in klines[-30:]]
    volumes = [float(k.get("volume", 0)) for k in klines[-30:]]

    recent_close = closes[-1]
    recent_high = max(highs[-10:])
    recent_low = min(float(k["low"]) for k in klines[-10:])
    avg_volume = sum(volumes[-20:]) / 20
    recent_vol = sum(volumes[-3:]) / 3

    breakout = False
    volume_confirmed = False
    score = 50.0
    reasons: list[str] = []

    # Breakout above recent high
    if recent_close > recent_high * 1.005:
        breakout = True
        pct_above = (recent_close / recent_high - 1) * 100
        score += 20
        reasons.append(f"突破10日高点({recent_high:.0f}，超{pct_above:.2f}%)")
    # Breakdown below recent low
    elif recent_close < recent_low * 0.995:
        breakout = True
        score += 15
        reasons.append(f"跌破10日低点({recent_low:.0f})")

    # Volume confirmation
    if recent_vol > avg_volume * 1.5:
        volume_confirmed = True
        score += 15
        reasons.append(f"放量{recent_vol/avg_volume:.1f}x")
    elif recent_vol > avg_volume * 1.2:
        volume_confirmed = True
        score += 8
        reasons.append(f"温和放量{recent_vol/avg_volume:.1f}x")
    else:
        score -= 5
        reasons.append("量能不足")

    # Trend strength from RSI/MA
    if indicators:
        rsi = indicators.get("rsi", 50)
        if 40 <= rsi <= 60:
            score += 10
            reasons.append(f"RSI中性偏强({rsi:.0f})")
        elif rsi > 70 and breakout:
            score -= 5
            reasons.append(f"RSI偏高({rsi:.0f})注意超买")
        ema9 = indicators.get("ema_9")
        ema21 = indicators.get("ema_21")
        if ema9 and ema21 and ema9 > ema21:
            score += 8
            reasons.append("EMA9>EMA21多头排列")
        elif ema9 and ema21:
            score -= 5
            reasons.append("EMA空头排列")

    score = max(10, min(95, score))
    priority = "high" if breakout and volume_confirmed and score >= 70 else \
               "medium" if breakout or volume_confirmed else "low"

    return OpportunitySignal(
        signal_type="breakout", symbol=symbol, priority=priority,
        score=round(score, 1), confidence=round(min(score / 100, 0.85), 2),
        kline_score=round(score, 1),
        breakout=breakout, volume_confirmed=volume_confirmed,
        summary="; ".join(reasons) if reasons else "无突破信号",
        scanner_meta=ScannerMetadata(scanner="breakout"),
    )


def scan_fund_flow(
    symbol: str,
    market_overview: list[dict[str, Any]] | None = None,
    klines: list[dict[str, Any]] | None = None,
) -> OpportunitySignal:
    """
    Scanner: 资金驱动 → 确认趋势真实性。

    fund_flow_score: 资金评分 0-100
    trend_support: 资金对趋势的支撑力度 0.0-1.0
    """
    if not market_overview and not klines:
        return OpportunitySignal(
            signal_type="fund_flow", symbol=symbol, priority="info",
            score=50, confidence=0.0, fund_flow_score=50, trend_support=0.0,
            summary="资金数据不可用",
            scanner_meta=ScannerMetadata(scanner="fund_flow", data_missing=True),
        )

    score = 50.0
    trend_support = 0.5
    reasons: list[str] = []

    # Market overview volume
    if market_overview:
        for item in market_overview:
            if item.get("symbol", "").upper() == symbol.upper():
                vol = item.get("volume_24h", 0)
                pct = item.get("price_change_24h_pct", 0)
                if vol and vol > 5e8:
                    score += 12
                    reasons.append(f"24h交易量{vol:.1e}，流动性充裕")
                    trend_support = min(1.0, trend_support + 0.2)
                if pct and abs(pct) > 5:
                    score += 5 if pct > 0 else -5
                    reasons.append(f"24h涨跌{pct:+.1f}%")
                    trend_support = min(1.0, trend_support + 0.1)
                break

    # Volume trend from klines
    if klines and len(klines) >= 20:
        recent_vols = [float(k.get("volume", 0)) for k in klines[-5:]]
        older_vols = [float(k.get("volume", 0)) for k in klines[-20:-5]]
        if sum(recent_vols) > sum(older_vols) / 3 * 5 * 1.3:
            score += 10
            reasons.append(f"近5期均量较前15期放量")
            trend_support = min(1.0, trend_support + 0.15)

        # Price-volume correlation
        closes = [float(k["close"]) for k in klines[-10:]]
        vols = [float(k.get("volume", 0)) for k in klines[-10:]]
        up_vol = sum(v for i, v in enumerate(vols) if i > 0 and closes[i] > closes[i-1])
        down_vol = sum(v for i, v in enumerate(vols) if i > 0 and closes[i] < closes[i-1])
        total_vol = up_vol + down_vol
        if total_vol > 0 and up_vol / total_vol > 0.6:
            score += 8
            reasons.append("上涨伴随放量，趋势健康")
            trend_support = min(1.0, trend_support + 0.2)
        elif total_vol > 0 and down_vol / total_vol > 0.6:
            score -= 8
            reasons.append("下跌伴随放量，资金流出")
            trend_support = max(0.0, trend_support - 0.2)

    score = max(10, min(95, score))
    priority = "high" if score >= 75 and trend_support >= 0.6 else \
               "medium" if score >= 60 else "low"

    return OpportunitySignal(
        signal_type="fund_flow", symbol=symbol, priority=priority,
        score=round(score, 1), confidence=round(trend_support, 2),
        fund_flow_score=round(score, 1), trend_support=round(trend_support, 2),
        summary="; ".join(reasons) if reasons else "资金流表现中性",
        scanner_meta=ScannerMetadata(scanner="fund_flow"),
    )
