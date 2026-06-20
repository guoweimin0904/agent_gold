"""Built-in trading strategies for the backtest engine.

Each strategy is a signal_fn compatible with SafeBacktestEngine.run().
Signature: ``signal_fn(ohlcv: list[dict], i: int) -> "buy" | "sell" | "hold"``
The function receives the full data list but MUST only use data[:i+1].
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

    # Extract close prices up to current candle (inclusive)
    closes = [float(c["close"]) for c in ohlcv[: i + 1]]

    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20

    # Previous candle's MAs (for crossover detection)
    if i >= 21:
        prev_closes = [float(c["close"]) for c in ohlcv[:i]]
        prev_ma5 = sum(prev_closes[-5:]) / 5
        prev_ma20 = sum(prev_closes[-20:]) / 20
    else:
        prev_ma5 = ma5
        prev_ma20 = ma5  # force first-time entry if ma5 > ma20

    # Golden cross: prev MA5 <= MA20, now MA5 > MA20
    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        logger.debug("Candle %d: MA5=%.2f crossed above MA20=%.2f → BUY", i, ma5, ma20)
        return "buy"

    # Death cross: prev MA5 >= MA20, now MA5 < MA20
    if prev_ma5 >= prev_ma20 and ma5 < ma20:
        logger.debug("Candle %d: MA5=%.2f crossed below MA20=%.2f → SELL", i, ma5, ma20)
        return "sell"

    return "hold"
