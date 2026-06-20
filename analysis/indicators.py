"""Technical indicators — built on pandas for vectorised calculation."""

import pandas as pd
import numpy as np


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD indicator — returns MACD line, signal line, histogram."""
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    })


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands."""
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    return pd.DataFrame({
        "upper": middle + std_dev * std,
        "middle": middle,
        "lower": middle - std_dev * std,
    })


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def add_all_indicators(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Add a comprehensive set of indicators to an OHLCV DataFrame."""
    df = ohlcv.copy()
    df["ema_9"] = ema(df["close"], 9)
    df["ema_21"] = ema(df["close"], 21)
    df["rsi"] = rsi(df["close"], 14)
    macd_df = macd(df["close"])
    df["macd"] = macd_df["macd"]
    df["macd_signal"] = macd_df["signal"]
    df["macd_hist"] = macd_df["histogram"]
    bb = bollinger_bands(df["close"])
    df["bb_upper"] = bb["upper"]
    df["bb_middle"] = bb["middle"]
    df["bb_lower"] = bb["lower"]
    df["atr"] = atr(df["high"], df["low"], df["close"], 14)
    df["obv"] = obv(df["close"], df["volume"])
    df["volume_sma_20"] = sma(df["volume"], 20)
    return df
