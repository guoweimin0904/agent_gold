"""Built-in trading strategies for the backtest engine.

Each strategy is a signal_fn compatible with SafeBacktestEngine.run().
Signature: ``signal_fn(ohlcv: list[dict], i: int) -> "buy" | "sell" | "short" | "cover" | "hold"``
The function receives the full data list but MUST only use data[:i+1].

Strategies:
  - ma5_20_crossover    — MA5/20 金叉死叉 (经典趋势)
  - rsi_mean_reversion  — RSI 均值回归 (震荡市抄底/摸顶)
  - macd_zero_cross     — MACD 零轴策略 (趋势确认)
  - bollinger_mean_rev  — 布林带回归 (波动率套利)
"""

import logging
from typing import Any

logger = logging.getLogger("backtest.strategies")


def ma5_20_crossover(
    ohlcv: list[dict[str, Any]],
    i: int,
) -> str:
    """
    MA5(close) × MA20(close) golden-cross / death-cross strategy.

    - Golden cross (MA5 crosses above MA20) → "buy"
    - Death cross (MA5 crosses below MA20) → "sell"
    - Otherwise → "hold"

    Only uses data up to index `i`. Needs at least 20 candles to compute MA20.
    """
    if i < 20:
        return "hold"

    closes = [float(c["close"]) for c in ohlcv[: i + 1]]

    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20

    if i >= 21:
        prev_closes = [float(c["close"]) for c in ohlcv[:i]]
        prev_ma5 = sum(prev_closes[-5:]) / 5
        prev_ma20 = sum(prev_closes[-20:]) / 20
    else:
        prev_ma5 = ma5
        prev_ma20 = ma5

    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        return "buy"
    if prev_ma5 >= prev_ma20 and ma5 < ma20:
        return "sell"
    return "hold"


def rsi_mean_reversion(
    ohlcv: list[dict[str, Any]],
    i: int,
) -> str:
    """
    RSI 均值回归策略 — 适应震荡市。

    - RSI < 25 (超卖) → "buy" (抄底)
    - RSI > 78 (超买) → "sell" (平多) / "short" (如果开了 short 信号档位)
    - RSI 回归 40-60 → "cover" (平空)
    - Otherwise → "hold"

    需要至少 15 根 K 线计算 RSI。
    """
    if i < 15:
        return "hold"

    closes = [float(c["close"]) for c in ohlcv[: i + 1]]

    # Simple RSI(14)
    deltas = [closes[j] - closes[j - 1] for j in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-14:]]
    losses = [-d if d < 0 else 0 for d in deltas[-14:]]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        rs = 100
    else:
        rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    if rsi < 25:
        return "buy"
    if rsi > 78:
        return "sell"
    return "hold"


def macd_zero_cross(
    ohlcv: list[dict[str, Any]],
    i: int,
) -> str:
    """
    MACD 零轴策略 — 趋势确认。

    - MACD 线上穿零轴 + EMA12 > EMA26 → "buy"
    - MACD 线下穿零轴 + EMA12 < EMA26 → "sell"
    - Otherwise → "hold"

    需要至少 35 根 K 线。
    """
    if i < 35:
        return "hold"

    closes = [float(c["close"]) for c in ohlcv[: i + 1]]

    # EMA(12) and EMA(26)
    def ema(data, period):
        k = 2 / (period + 1)
        result = data[0]
        for v in data[1:]:
            result = v * k + result * (1 - k)
        return result

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = ema12 - ema26
    # Signal line: EMA(9) of MACD
    # Simplified: compare macd_line to zero

    # Previous bar MACD
    if i >= 27:
        prev_closes = closes[:-1]
        prev_ema12 = ema(prev_closes, 12)
        prev_ema26 = ema(prev_closes, 26)
        prev_macd = prev_ema12 - prev_ema26
    else:
        prev_macd = macd_line

    # MACD crosses above zero
    if prev_macd <= 0 and macd_line > 0 and ema12 > ema26:
        return "buy"
    # MACD crosses below zero
    if prev_macd >= 0 and macd_line < 0 and ema12 < ema26:
        return "sell"
    return "hold"


def bollinger_mean_rev(
    ohlcv: list[dict[str, Any]],
    i: int,
) -> str:
    """
    布林带均值回归策略 — 波动率套利。

    - 收盘价跌破布林下轨 → "buy" (超卖反弹)
    - 收盘价突破布林上轨 → "sell" (超买回调)
    - Otherwise → "hold"

    需要至少 21 根 K 线。
    """
    if i < 21:
        return "hold"

    closes = [float(c["close"]) for c in ohlcv[: i + 1]]
    n = min(20, len(closes))

    # 20-period SMA and std
    recent = closes[-n:]
    sma = sum(recent) / n
    variance = sum((x - sma) ** 2 for x in recent) / n
    std = variance ** 0.5

    upper = sma + 2 * std
    lower = sma - 2 * std
    current = closes[-1]

    # Below lower band → buy (oversold)
    if current < lower:
        return "buy"
    # Above upper band → sell (overbought)
    if current > upper:
        return "sell"
    return "hold"
