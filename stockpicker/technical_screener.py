"""A-Share technical screener — trend, momentum, volume, support/resistance.

Uses kline data in the same unified format as the rest of the system.
"""

import logging
from typing import Any

from stockpicker.schemas import TechnicalScore

logger = logging.getLogger("stockpicker.technical")


def score_technical(
    klines: list[dict[str, Any]] | None = None,
    indicators: dict[str, Any] | None = None,
) -> TechnicalScore:
    """
    A-share technical scoring.

    trend: MA alignment, slope
    momentum: RSI, MACD
    volume: volume ratio vs 20d avg
    support/resist: BB zone, recent range
    """
    if not klines or len(klines) < 20:
        return TechnicalScore(
            total=50, summary="技术数据不足，默认中性"
        )

    closes = [float(k["close"]) for k in klines[-30:]]
    volumes = [float(k.get("volume", 0)) for k in klines[-30:]]
    highs = [float(k["high"]) for k in klines[-30:]]
    lows = [float(k["low"]) for k in klines[-30:]]

    recent = closes[-1]
    reasons: list[str] = []

    # ── Trend score (0-100) ──
    trend = 50.0
    slope = (closes[-1] - closes[0]) / closes[0] * 100
    if slope > 8:
        trend = 85
        reasons.append(f"强势上涨({slope:+.1f}%)")
    elif slope > 3:
        trend = 70
        reasons.append(f"趋势向上({slope:+.1f}%)")
    elif slope > 0:
        trend = 55
    elif slope > -3:
        trend = 40
        reasons.append(f"弱势下跌({slope:.1f}%)")
    elif slope > -8:
        trend = 25
        reasons.append(f"下跌趋势({slope:.1f}%)")
    else:
        trend = 10
        reasons.append(f"暴跌({slope:.1f}%)")

    # MA cross (if indicators available)
    if indicators:
        ema5 = indicators.get("ema_5")
        ema20 = indicators.get("ema_20")
        if ema5 and ema20:
            if ema5 > ema20:
                trend += 8
                reasons.append("5日线>20日线")
            else:
                trend -= 5

    # ── Momentum score ──
    momentum = 50.0
    rsi = (indicators or {}).get("rsi", 50)
    if rsi < 25:
        momentum = 15
        reasons.append(f"RSI={rsi:.0f} 严重超卖")
    elif rsi < 35:
        momentum = 30
        reasons.append(f"RSI={rsi:.0f} 超卖")
    elif rsi < 45:
        momentum = 45
    elif rsi < 55:
        momentum = 55
    elif rsi < 65:
        momentum = 60
    elif rsi < 75:
        momentum = 45
        reasons.append(f"RSI={rsi:.0f} 偏高")
    else:
        momentum = 20
        reasons.append(f"RSI={rsi:.0f} 严重超买")

    macd_hist = indicators.get("macd_hist", 0) if indicators else 0
    if macd_hist > 0:
        momentum += 8
        reasons.append("MACD多头")
    elif macd_hist < 0:
        momentum -= 5
        reasons.append("MACD空头")

    # ── Volume score ──
    volume = 50.0
    avg_vol20 = sum(volumes[-20:]) / 20
    avg_vol5 = sum(volumes[-5:]) / 5
    vol_ratio = avg_vol5 / avg_vol20 if avg_vol20 > 0 else 1

    if vol_ratio > 2:
        volume = 80
        reasons.append(f"放量{vol_ratio:.1f}x")
    elif vol_ratio > 1.5:
        volume = 70
        reasons.append(f"温和放量{vol_ratio:.1f}x")
    elif vol_ratio > 0.7:
        volume = 50
    elif vol_ratio > 0.4:
        volume = 30
        reasons.append(f"缩量{vol_ratio:.1f}x")
    else:
        volume = 15
        reasons.append(f"极度缩量{vol_ratio:.1f}x")

    # ── Support/Resistance score ──
    sr = 50.0
    recent_high = max(highs[-10:])
    recent_low = min(lows[-10:])
    range_pct = (recent_high - recent_low) / recent_low * 100

    if range_pct < 3:
        sr = 35
        reasons.append("窄幅震荡")
    elif range_pct < 6:
        sr = 45
    elif range_pct < 10:
        sr = 55
    else:
        sr = 40
        reasons.append(f"波动过大幅({range_pct:.1f}%)")

    # BB zone
    bb_lower = (indicators or {}).get("bb_lower")
    bb_upper = (indicators or {}).get("bb_upper")
    if bb_lower and recent <= bb_lower * 1.02:
        sr += 12
        reasons.append("触及布林下轨(支撑)")
    if bb_upper and recent >= bb_upper * 0.98:
        sr -= 10
        reasons.append("触及布林上轨(压力)")

    # ── Weighted total ──
    total = trend * 0.35 + momentum * 0.30 + volume * 0.20 + sr * 0.15
    total = max(5, min(95, total))

    summary = "; ".join(reasons) if reasons else "技术面中性"

    return TechnicalScore(
        trend_score=round(trend, 1),
        momentum_score=round(momentum, 1),
        volume_score=round(volume, 1),
        support_resist=round(sr, 1),
        total=round(total, 1),
        summary=summary,
    )
