"""News connector — pull crypto news from multiple free sources with retry & fallback."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from config import DataLayerConfig, NewsAPIConfig
from connectors.base import NewsItem, make_session, with_retry

logger = logging.getLogger("connectors.news")

CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"
COINGECKO_NEWS_URL = "https://api.coingecko.com/api/v3/news"


class NewsData:
    """Read-only news data accessor. Tries multiple sources."""

    def __init__(self) -> None:
        self.cfg = NewsAPIConfig()
        self.dl_cfg = DataLayerConfig()
        self._session = make_session()
        if self.cfg.api_key:
            self._session.headers.update({"x-cg-pro-api-key": self.cfg.api_key})

    # ── Primary: CoinGecko News (free, no key required for basic) ─────

    @with_retry()
    def fetch_all(
        self,
        hours: int = 24,
        limit: int = 20,
    ) -> list[NewsItem]:
        """
        Fetch news from all available sources.
        Returns unified NewsItem list. Never returns None — missing is ok.
        """
        items: list[NewsItem] = []

        # Try CoinGecko news (free)
        try:
            cg_items = self._fetch_coingecko_news(limit)
            items.extend(cg_items)
            logger.info("CoinGecko news returned %d items", len(cg_items))
        except Exception as e:
            logger.warning("CoinGecko news failed: %s", e)

        # Try CryptoPanic if we need more items
        if len(items) < limit:
            try:
                cp_items = self._fetch_cryptopanic("BTC,ETH", limit - len(items))
                items.extend(cp_items)
            except Exception as e:
                logger.warning("CryptoPanic fallback also failed: %s", e)

        # Filter by recency
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        items = [i for i in items if self._within_window(i.published_at, since)]

        # Mark missing if still empty
        if not items:
            logger.info("No news items from any source — marking as missing")
            items.append(
                NewsItem(
                    title="",
                    url="",
                    published_at=datetime.now(timezone.utc).isoformat(),
                    source="aggregated",
                    status="missing",
                    summary="No news sources returned data",
                )
            )

        return items[:limit]

    def _fetch_coingecko_news(self, limit: int) -> list[NewsItem]:
        """Fetch news via CoinGecko news endpoint (free tier)."""
        resp = self._session.get(
            COINGECKO_NEWS_URL,
            params={"per_page": min(limit, 50)},
            timeout=self.dl_cfg.request_timeout,
        )
        resp.raise_for_status()
        raw_items: list[dict[str, Any]] = resp.json()

        items: list[NewsItem] = []
        for r in raw_items:
            try:
                items.append(
                    NewsItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        published_at=r.get(
                            "created_at",
                            datetime.now(timezone.utc).isoformat(),
                        ),
                        source="coingecko_news",
                        summary=r.get("description", r.get("title", "")),
                        status="ok" if r.get("title") else "missing",
                    )
                )
            except Exception as e:
                logger.warning("Skipping malformed CoinGecko news: %s", e)
                continue
        return items

    # ── Fallback: CryptoPanic (requires API key) ──────────────────────

    def _fetch_cryptopanic(self, currencies: str, limit: int) -> list[NewsItem]:
        """Fetch news from CryptoPanic. Falls back gracefully."""
        params: dict[str, Any] = {
            "currencies": currencies,
            "limit": limit,
        }
        if self.cfg.api_key:
            params["auth_token"] = self.cfg.api_key
            resp = self._session.get(
                CRYPTOPANIC_URL,
                params=params,
                timeout=self.dl_cfg.request_timeout,
            )
            resp.raise_for_status()
            raw_items = resp.json().get("results", [])
        else:
            # CryptoPanic public endpoint no longer works (404)
            logger.info("CryptoPanic API key not set — skipping")
            return []

        items: list[NewsItem] = []
        for r in raw_items:
            try:
                pub_str = r.get("published_at", "")
                if not pub_str:
                    continue
                items.append(
                    NewsItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        published_at=datetime.fromisoformat(
                            pub_str.replace("Z", "+00:00")
                        ).isoformat(),
                        source="cryptopanic",
                        summary=r.get("title", ""),
                        status="ok" if r.get("title") else "missing",
                    )
                )
            except Exception:
                continue
        return items

    @staticmethod
    def _within_window(pub_iso: str, since: datetime) -> bool:
        """Check if a published date is within the recency window."""
        try:
            pub_dt = datetime.fromisoformat(pub_iso.replace("Z", "+00:00"))
            return pub_dt >= since
        except Exception:
            return False
