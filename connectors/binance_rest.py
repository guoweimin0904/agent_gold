"""Binance REST connector — READ-ONLY Kline & ticker data. No order capability."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

from config import BinanceConfig, DataLayerConfig
from connectors.base import Kline, MarketOverviewItem, make_session, with_retry

logger = logging.getLogger("connectors.binance")

# Public endpoints only — NO spot/testnet ordering endpoints
BASE_URL = "https://api.binance.com/api/v3"


class BinanceData:
    """Read-only Binance data accessor. Cannot place orders."""

    def __init__(self, config: BinanceConfig | None = None) -> None:
        self.cfg = config or BinanceConfig()
        self.dl_cfg = DataLayerConfig()
        self._session = make_session()

    # ── Klines ───────────────────────────────────────────────────────

    @with_retry()
    def get_klines(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
    ) -> list[Kline]:
        """
        Fetch unified Kline data.

        Returns normalized Kline objects regardless of Binance's raw format.
        """
        raw = self._fetch_klines_raw(symbol, interval, limit)
        return [self._parse_kline(row, symbol, interval) for row in raw]

    def _fetch_klines_raw(
        self, symbol: str, interval: str, limit: int
    ) -> list[list[Any]]:
        params = {
            "symbol": symbol.upper().replace("-", ""),
            "interval": interval,
            "limit": min(limit, 1000),
        }
        resp = self._session.get(
            f"{BASE_URL}/klines",
            params=params,
            timeout=self.dl_cfg.request_timeout,
        )
        resp.raise_for_status()
        data: list[list[Any]] = resp.json()
        return data

    @staticmethod
    def _parse_kline(raw: list[Any], symbol: str, interval: str) -> Kline:
        """
        Binance raw kline format:
        [open_time, open, high, low, close, volume, close_time, ...]
        """
        return Kline(
            timestamp=datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc).isoformat(),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            source="binance",
            symbol=symbol.upper(),
            interval=interval,
        )

    # ── Ticker / 24hr ────────────────────────────────────────────────

    @with_retry()
    def get_ticker_price(self, symbol: str) -> Decimal | None:
        """Fetch latest price. Returns None on failure."""
        try:
            params = {"symbol": symbol.upper().replace("-", "")}
            resp = self._session.get(
                f"{BASE_URL}/ticker/price",
                params=params,
                timeout=self.dl_cfg.request_timeout,
            )
            resp.raise_for_status()
            return Decimal(resp.json()["price"])
        except Exception as e:
            logger.error("Failed to fetch ticker price for %s: %s", symbol, e)
            return None

    @with_retry()
    def get_24hr_ticker(self, symbol: str) -> MarketOverviewItem | None:
        """Fetch 24hr ticker stats. Returns None on failure."""
        try:
            params = {"symbol": symbol.upper().replace("-", "")}
            resp = self._session.get(
                f"{BASE_URL}/ticker/24hr",
                params=params,
                timeout=self.dl_cfg.request_timeout,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return MarketOverviewItem(
                symbol=symbol.upper(),
                price=float(data.get("lastPrice", 0)),
                price_change_24h_pct=float(data.get("priceChangePercent", 0)),
                volume_24h=float(data.get("quoteVolume", 0)),
                source="binance",
            )
        except Exception as e:
            logger.error("Failed to fetch 24hr ticker for %s: %s", symbol, e)
            return None
