"""CoinGecko connector — market overview & price data only. Read-only."""
from __future__ import annotations

import logging
from typing import Any

import requests

from config import CoinGeckoConfig, DataLayerConfig
from connectors.base import (
    Kline,
    MarketOverviewItem,
    make_session,
    with_retry,
)

logger = logging.getLogger("connectors.coingecko")

BASE_URL = "https://api.coingecko.com/api/v3"


class CoinGeckoData:
    """Read-only CoinGecko market data accessor."""

    def __init__(self, config: CoinGeckoConfig | None = None) -> None:
        self.cfg = config or CoinGeckoConfig()
        self.dl_cfg = DataLayerConfig()
        self._session = make_session()
        if self.cfg.api_key:
            self._session.headers.update({"x-cg-pro-api-key": self.cfg.api_key})

    # ── Klines (via OHLC endpoint) ───────────────────────────────────

    @with_retry()
    def get_klines(
        self,
        coin_id: str = "bitcoin",
        vs_currency: str = "usd",
        days: int = 7,
    ) -> list[Kline]:
        """
        Fetch OHLC data as unified Klines.

        CoinGecko OHLC returns: [timestamp_ms, open, high, low, close]
        No volume included — volume will be 0.0 and marked.
        """
        raw = self._fetch_ohlc_raw(coin_id, vs_currency, days)
        return [self._parse_kline(row, coin_id, days) for row in raw]

    def _fetch_ohlc_raw(
        self, coin_id: str, vs_currency: str, days: int
    ) -> list[list[float]]:
        params = {"vs_currency": vs_currency, "days": str(days)}
        resp = self._session.get(
            f"{BASE_URL}/coins/{coin_id}/ohlc",
            params=params,
            timeout=self.dl_cfg.request_timeout,
        )
        resp.raise_for_status()
        data: list[list[float]] = resp.json()
        return data

    @staticmethod
    def _parse_kline(raw: list[float], coin_id: str, days: int) -> Kline:
        from datetime import datetime, timezone

        ts_ms = raw[0]
        dt_obj = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        symbol_map = {
            "bitcoin": "BTCUSDT",
            "ethereum": "ETHUSDT",
        }
        return Kline(
            timestamp=dt_obj.isoformat(),
            open=raw[1],
            high=raw[2],
            low=raw[3],
            close=raw[4],
            volume=0.0,  # CoinGecko OHLC excludes volume
            source="coingecko",
            symbol=symbol_map.get(coin_id, coin_id.upper()),
            interval=f"{days}d",
        )

    # ── Market overview ──────────────────────────────────────────────

    @with_retry()
    def get_market_overview(
        self,
        vs_currency: str = "usd",
        per_page: int = 10,
    ) -> list[MarketOverviewItem]:
        """
        Fetch top coins market data as unified MarketOverviewItems.
        Returns empty list on total failure — each item is self-reporting.
        """
        try:
            raw = self._fetch_markets_raw(vs_currency, per_page)
            return [self._parse_market_item(c, vs_currency) for c in raw]
        except Exception as e:
            logger.error("CoinGecko market overview failed: %s", e)
            return []

    def _fetch_markets_raw(
        self, vs_currency: str, per_page: int
    ) -> list[dict[str, Any]]:
        params = {
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "per_page": str(per_page),
            "sparkline": "false",
        }
        resp = self._session.get(
            f"{BASE_URL}/coins/markets",
            params=params,
            timeout=self.dl_cfg.request_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_market_item(raw: dict[str, Any], vs_currency: str) -> MarketOverviewItem:
        from connectors.base import MarketOverviewItem

        price = raw.get("current_price")
        return MarketOverviewItem(
            symbol=(raw.get("symbol", "???").upper()),
            price=float(price) if price is not None else None,
            price_change_24h_pct=raw.get("price_change_percentage_24h"),
            market_cap=raw.get("market_cap"),
            volume_24h=raw.get("total_volume"),
            source="coingecko",
            status="ok" if price is not None else "missing",
        )

    # ── Trending (optional extra) ────────────────────────────────────

    @with_retry()
    def get_trending(self) -> list[dict[str, Any]]:
        try:
            resp = self._session.get(
                f"{BASE_URL}/search/trending",
                timeout=self.dl_cfg.request_timeout,
            )
            resp.raise_for_status()
            return resp.json().get("coins", [])
        except Exception as e:
            logger.error("CoinGecko trending failed: %s", e)
            return []
