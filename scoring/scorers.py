"""7 sub-scorers — each computes one dimension of the scoring report.

All return a ScoredDimension with score 0-100, reason, and data_available flag.
"""

import logging
from typing import Any

from scoring.schemas import ScoredDimension

logger = logging.getLogger("scoring.scorers")


# ── 1. Event Score ──────────────────────────────────────────────────

def score_event(news_report: dict[str, Any] | None) -> ScoredDimension:
    """
    Score from news monitoring pipeline.

    S = 60-100, A = 40-70, B = 20-50, C = 0-20.
    Risk pause → score clamped low.
    """
    if not news_report or not news_report.get("reports"):
        return ScoredDimension(
            name="event_score", score=30, weight=1.0,
            reason="无新闻数据，按中性默认值处理",
            data_available=False, data_missing=True,
        )

    reports = news_report["reports"]
    if not reports:
        return ScoredDimension(
            name="event_score", score=30, weight=1.0, reason="无新闻事件",
        )

    # Score the most impactful event
    max_score = 0.0
    best_reason = ""
    for r in reports:
        level = r.get("impact_level", "C")
        direction = r.get("direction", "neutral")
        risk_pause = r.get("risk_pause", False)
        cred = r.get("credibility", 0.3)

        base = {"S": 80, "A": 55, "B": 35, "C": 10}.get(level, 10)
        # Direction bonus
        if direction == "bullish":
            dir_mod = +10
        elif direction == "bearish":
            dir_mod = -5
        else:
            dir_mod = 0
        # Credibility multiplier
        cred_mod = base * (cred - 0.5) * 0.5
        score = max(0, min(100, base + dir_mod + cred_mod))

        if risk_pause:
            score = min(score, 20)  # risk pause → score capped low

        if score > max_score:
            max_score = score
            best_reason = r.get("summary", r.get("title", ""))[:80]

    return ScoredDimension(
        name="event_score",
        score=round(max_score, 1),
        weight=1.0,
        reason=best_reason or "最高影响事件评分",
    )


# ── 2. Sentiment Score ─────────────────────────────────────────────

def score_sentiment(
    news_report: dict[str, Any] | None,
    market_overview: list[dict[str, Any]] | None = None,
) -> ScoredDimension:
    """
    Aggregate sentiment from news + market overview.
    Uses direction credibility-weighted aggregation.
    """
    bullish_total = 0.0
    bearish_total = 0.0
    neutral_count = 0
    weighted_sum = 0.0
    total_weight = 0.0

    direction_map = {"bullish": 1.0, "bearish": -1.0, "mixed": 0.0, "neutral": 0.0}

    if news_report and news_report.get("reports"):
        for r in news_report["reports"]:
            d = r.get("direction", "neutral")
            cred = r.get("credibility", 0.3)
            val = direction_map.get(d, 0.0)
            weighted_sum += val * cred
            total_weight += cred
            if d == "bullish":
                bullish_total += cred
            elif d == "bearish":
                bearish_total += cred
            else:
                neutral_count += 1

    if total_weight == 0:
        return ScoredDimension(
            name="sentiment_score", score=50, weight=1.0,
            reason="新闻情感数据不可用，默认中性50分",
            data_available=False, data_missing=True,
        )

    # Score: -1 to +1 → 0 to 100
    raw_dir = weighted_sum / total_weight  # -1.0 to +1.0
    sent_score = (raw_dir + 1) * 50  # 0 to 100
    sent_score = max(10, min(90, sent_score))  # clamp, never extremes without strong evidence

    ratio = bullish_total / (bearish_total + 1)
    if ratio > 2:
        detail = f"看多/看空比 {ratio:.1f}x"
    elif bearish_total > bullish_total:
        detail = f"偏空 sentiment ({bearish_total:.1f} vs {bullish_total:.1f})"
    else:
        detail = f"neutral ({neutral_count}条中性)"

    return ScoredDimension(
        name="sentiment_score",
        score=round(sent_score, 1),
        weight=1.0,
        reason=f"情感聚合评分: {detail}",
    )


# ── 3. K-line Score ────────────────────────────────────────────────

def score_kline(
    klines: list[dict[str, Any]] | None,
    latest_price: float | None = None,
) -> ScoredDimension:
    """
    K-line pattern / price action scoring.
    Uses recent price trend, volatility, and candle patterns.
    """
    if not klines or len(klines) < 20:
        return ScoredDimension(
            name="kline_score", score=50, weight=1.0,
            reason="K线数据不足，按中性50分处理",
            data_available=False, data_missing=True,
        )

    closes = [float(k["close"]) for k in klines[-20:]]
    highs = [float(k["high"]) for k in klines[-20:]]
    lows = [float(k["low"]) for k in klines[-20:]]

    # Trend: slope of last 20 closes
    slope = (closes[-1] - closes[0]) / closes[0] * 100  # %
    if slope > 3:
        trend_score = 70 + min(slope * 2, 25)  # strong uptrend
    elif slope > 0:
        trend_score = 55 + slope * 5
    elif slope > -3:
        trend_score = 45 + slope * 3  # mild downtrend
    else:
        trend_score = max(10, 40 + slope * 2)  # strong downtrend

    # Volatility adjustment: too volatile = risky
    range_pcts = [(h - l) / l * 100 for h, l in zip(highs, lows)]
    avg_range = sum(range_pcts) / len(range_pcts)
    if avg_range > 3:
        trend_score -= 15  # high vol penalty
    elif avg_range > 1.5:
        trend_score -= 5

    score = max(0, min(100, trend_score))
    return ScoredDimension(
        name="kline_score",
        score=round(score, 1),
        weight=1.0,
        reason=f"20周期趋势 {slope:+.2f}%，波动率 {avg_range:.2f}%",
    )


# ── 4. Technical Score ──────────────────────────────────────────────

def score_technical(
    latest_indicators: dict[str, Any] | None,
) -> ScoredDimension:
    """
    Score from technical indicator confluence.
    RSI, MACD, MA cross, Bollinger, ATR.
    """
    if not latest_indicators:
        return ScoredDimension(
            name="technical_score", score=50, weight=1.0,
            reason="技术指标数据不可用，默认中性50分",
            data_available=False, data_missing=True,
        )

    score = 50.0
    reasons: list[str] = []

    # RSI
    rsi_val = latest_indicators.get("rsi")
    if rsi_val is not None:
        if 30 <= rsi_val <= 40:
            score += 12
            reasons.append(f"RSI={rsi_val:.0f} 接近超卖")
        elif 40 < rsi_val <= 60:
            score += 5
            reasons.append(f"RSI={rsi_val:.0f} 中性偏强")
        elif rsi_val < 30:
            score += 3
            reasons.append(f"RSI={rsi_val:.0f} 超卖(需确认)")
        elif 60 < rsi_val <= 70:
            score -= 5
            reasons.append(f"RSI={rsi_val:.0f} 偏高")
        elif rsi_val > 70:
            score -= 10
            reasons.append(f"RSI={rsi_val:.0f} 超买")

    # MACD
    macd_hist = latest_indicators.get("macd_hist")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 8
            reasons.append("MACD 多头")
        else:
            score -= 5
            reasons.append("MACD 空头")

    # MA cross (if available)
    ema_9 = latest_indicators.get("ema_9")
    ema_21 = latest_indicators.get("ema_21")
    if ema_9 and ema_21:
        if ema_9 > ema_21:
            score += 10
            reasons.append(f"EMA9({ema_9:.0f}) > EMA21({ema_21:.0f}) 金叉")
        else:
            score -= 5
            reasons.append(f"EMA9({ema_9:.0f}) < EMA21({ema_21:.0f}) 死叉")

    # Bollinger Band
    close = latest_indicators.get("close")
    bb_lower = latest_indicators.get("bb_lower")
    bb_upper = latest_indicators.get("bb_upper")
    if close and bb_lower and bb_upper:
        bb_width = (bb_upper - bb_lower) / ((bb_upper + bb_lower) / 2)
        if bb_width < 0.05:
            score += 5
            reasons.append("布林带收窄(即将突破)")
        elif close <= bb_lower * 1.02:
            score += 8
            reasons.append("触及布林下轨")
        elif close >= bb_upper * 0.98:
            score -= 8
            reasons.append("触及布林上轨")

    return ScoredDimension(
        name="technical_score",
        score=round(max(0, min(100, score)), 1),
        weight=1.0,
        reason="; ".join(reasons) or "无显著技术信号",
    )


# ── 5. Fund Flow Score ─────────────────────────────────────────────

def score_fund_flow(
    market_overview: list[dict[str, Any]] | None,
    symbol: str = "",
) -> ScoredDimension:
    """
    Fund flow / volume scoring from market overview and exchange data.
    """
    if not market_overview:
        return ScoredDimension(
            name="fund_flow_score", score=50, weight=1.0,
            reason="资金流数据不可用",
            data_available=False, data_missing=True,
        )

    score = 50.0
    vol_ratio = 1.0

    for item in market_overview:
        if item.get("symbol", "").upper() == symbol.upper():
            vol = item.get("volume_24h")
            price_change = item.get("price_change_24h_pct")
            if vol and vol > 1e8:
                score += 10
            if price_change and abs(price_change) > 5:
                score -= 5  # large moves = less reliable
            break

    return ScoredDimension(
        name="fund_flow_score",
        score=round(max(0, min(100, score)), 1),
        weight=1.0,
        reason=f"24h交易量倍数: {vol_ratio:.1f}x",
    )


# ── 6. Backtest Score ───────────────────────────────────────────────

def score_backtest(
    backtest_result: dict[str, Any] | None,
) -> ScoredDimension:
    """
    Score from most recent backtest run.
    """
    if not backtest_result:
        return ScoredDimension(
            name="backtest_score", score=50, weight=1.0,
            reason="回测数据不可用，默认中性",
            data_available=False, data_missing=True,
        )

    total_return = backtest_result.get("total_return_pct", 0)
    max_dd = backtest_result.get("max_drawdown_pct", 0)
    win_rate = backtest_result.get("win_rate", 0)
    profit_factor = backtest_result.get("profit_factor", 1.0)
    trade_count = backtest_result.get("trade_count", 0)
    sample_sufficient = backtest_result.get("sample_sufficient", False)

    if not sample_sufficient or trade_count < 30:
        return ScoredDimension(
            name="backtest_score", score=40, weight=1.0,
            reason=f"样本不足({trade_count}笔)，回测不可靠，默认保守40分",
        )

    score = 50.0
    reasons: list[str] = []

    # Return
    if total_return > 10:
        score += 20
        reasons.append(f"回测收益率 {total_return:+.1f}% > 10%")
    elif total_return > 0:
        score += 10
        reasons.append(f"回测正收益 {total_return:+.1f}%")
    elif total_return < -10:
        score -= 20
        reasons.append(f"回测大幅亏损 {total_return:.1f}%")
    else:
        score -= 10
        reasons.append(f"回测微亏 {total_return:.1f}%")

    # Max drawdown
    if max_dd < 10:
        score += 10
        reasons.append(f"最大回撤 < 10%")
    elif max_dd > 25:
        score -= 15
        reasons.append(f"最大回撤 {max_dd:.1f}% > 25%")

    # Win rate
    if win_rate > 0.6:
        score += 10
        reasons.append(f"胜率 > 60%")
    elif win_rate < 0.4:
        score -= 5

    # Profit factor
    if profit_factor != float("inf") and profit_factor > 2:
        score += 10
        reasons.append(f"盈亏比 > 2")
    elif profit_factor != float("inf") and profit_factor < 1:
        score -= 5

    return ScoredDimension(
        name="backtest_score",
        score=round(max(0, min(100, score)), 1),
        weight=1.0,
        reason="; ".join(reasons) or "回测结果中性",
    )


# ── 7. Risk Deduction ──────────────────────────────────────────────

def score_risk(
    risk_status: dict[str, Any] | None,
) -> ScoredDimension:
    """
    Risk penalty (deduction from total).

    Returns a ScoredDimension where score is the *deduction* amount (0-100).
    This is subtracted from the raw total.
    """
    deduction = 0.0
    reasons: list[str] = []

    if not risk_status:
        return ScoredDimension(
            name="risk_deduction", score=5, weight=1.0,
            reason="风控状态未知，加5分风险扣除",
            data_available=False, data_missing=True,
        )

    # Kill switch
    if risk_status.get("kill_switch_active", False):
        deduction += 50
        reasons.append("杀开关触发(-50)")

    # Daily loss limit
    if risk_status.get("daily_loss_limit_hit", False):
        deduction += 30
        reasons.append("日亏损上限触发(-30)")

    # High volatility
    if risk_status.get("high_volatility", False):
        deduction += 15
        reasons.append("高波动率(-15)")

    # S-level news event with risk_pause
    if risk_status.get("s_event_active", False):
        deduction += 40
        reasons.append("S级事件风险暂停(-40)")

    # Market-wide drawdown
    mdd = risk_status.get("market_drawdown_pct", 0)
    if mdd > 15:
        deduction += 20
        reasons.append(f"市场回撤 {mdd:.1f}%(-20)")

    # Default small deduction for baseline risk
    if not reasons:
        deduction = 5
        reasons.append("基准风控扣除(-5)")

    return ScoredDimension(
        name="risk_deduction",
        score=round(min(100, deduction), 1),
        weight=1.0,
        reason="; ".join(reasons),
    )
