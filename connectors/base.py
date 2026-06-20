"""Shared base: retry wrapper + unified Kline/RawData models + logging."""

from __future__ import annotations

import functools
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, TypeVar

import requests

from config import DataLayerConfig

logger = logging.getLogger("connectors")

F = TypeVar("F", bound=Callable[..., Any])


# ── Retry decorator ──────────────────────────────────────────────────

def with_retry(
    max_attempts: int | None = None,
    base_delay: float | None = None,
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff + jitter."""
    cfg = DataLayerConfig()
    attempts = max_attempts if max_attempts is not None else cfg.retry_max
    delay = base_delay if base_delay is not None else cfg.retry_delay

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except requests.Timeout as e:
                    last_exc = e
                    logger.warning(
                        "Timeout on %s (attempt %d/%d)", func.__name__, attempt, attempts
                    )
                except requests.RequestException as e:
                    last_exc = e
                    resp = getattr(e, "response", None)
                    status = resp.status_code if resp is not None else "N/A"
                    logger.warning(
                        "HTTP %s on %s (attempt %d/%d): %s",
                        status, func.__name__, attempt, attempts, e,
                    )
                    # Non-retryable statuses
                    if resp is not None and resp.status_code in (400, 401, 403, 404):
                        raise
                except Exception as e:
                    last_exc = e
                    logger.error(
                        "Unexpected error on %s (attempt %d/%d): %s",
                        func.__name__, attempt, attempts, e,
                    )
                    raise  # don't retry on unexpected errors

                if attempt < attempts:
                    jittered = delay * (2 ** (attempt - 1)) * (0.5 + random.random())
                    time.sleep(jittered)

            raise RuntimeError(
                f"{func.__name__} failed after {attempts} attempts"  # noqa: B023
            ) from last_exc

        return wrapper  # type: ignore

    return decorator


# ── Unified Kline data model ────────────────────────────────────────

@dataclass
class Kline:
    timestamp: str        # ISO-8601
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str           # "binance" | "coingecko" | ...
    symbol: str           # "BTCUSDT" | "ETHUSDT"
    interval: str         # "1m", "5m", "15m", "1h", "4h", "1d"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Unified Market Overview data model ──────────────────────────────

@dataclass
class MarketOverviewItem:
    symbol: str
    price: float | None = None
    price_change_24h_pct: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    source: str = "coingecko"
    status: str = "ok"  # "ok" | "missing"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.price is None:
            d["status"] = "missing"
        return d


# ── Unified News data model ─────────────────────────────────────────

@dataclass
class NewsItem:
    title: str
    url: str
    published_at: str          # ISO-8601
    source: str                # "cryptopanic" | "x_twitter"
    summary: str = ""
    sentiment_score: float | None = None
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not self.title:
            d["status"] = "missing"
        return d


# ── Helper: safe session ────────────────────────────────────────────

def make_session(timeout: int | None = None) -> requests.Session:
    cfg = DataLayerConfig()
    s = requests.Session()
    s.timeout = timeout or cfg.request_timeout
    return s
