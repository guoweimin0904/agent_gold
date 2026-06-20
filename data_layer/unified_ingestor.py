"""Unified ingestor — orchestrates all read-only data sources into MarketSnapshot."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import BASE_DIR
from connectors.base import logger as base_logger
from connectors.binance_rest import BinanceData
from connectors.coingecko import CoinGeckoData
from connectors.news_source import NewsData
from connectors.x_watchlist import XWatchlistData
from data_layer.market_snapshot import MarketSnapshot, SourceMetadata
from data_layer.news_collector import MultiSourceNewsCollector

logger = logging.getLogger("data_layer.ingestor")

SNAPSHOT_PATH = BASE_DIR / "data" / "market_snapshot.json"


class DataIngestor:
    """Orchestrates all data sources and produces a unified market_snapshot.json."""

    def __init__(self) -> None:
        self.binance = BinanceData()
        self.coingecko = CoinGeckoData()
        self.news = NewsData()
        self.multi_news = MultiSourceNewsCollector()
        # X requires bearer token — will auto-mark missing without it
        self.xwatch = XWatchlistData(bearer_token=None)

        self.symbols = ["BTCUSDT", "ETHUSDT"]

    def ingest(self) -> MarketSnapshot:
        """Fetch all data, build snapshot, write to disk, return snapshot."""
        logger.info("Starting data ingestion cycle")

        snapshot = MarketSnapshot(symbols=self.symbols)
        meta_list: list[SourceMetadata] = []

        # ── 1. Binance klines ─────────────────────────────────────
        binance_meta = SourceMetadata(source="binance", status="ok")
        binance_klines: list[dict[str, Any]] = []
        for sym in self.symbols:
            try:
                klines = self.binance.get_klines(symbol=sym, interval="1h", limit=100)
                binance_klines.extend(k.to_dict() for k in klines)
                binance_meta.klines_count += len(klines)
            except Exception as e:
                logger.error("Binance klines failed for %s: %s", sym, e)
                binance_meta.status = "error"
                binance_meta.error_message = str(e)

        # Binance overview (24hr ticker)
        for sym in self.symbols:
            try:
                item = self.binance.get_24hr_ticker(sym)
                if item is not None:
                    snapshot.market_overview.append(item.to_dict())
                    binance_meta.overview_count += 1
            except Exception as e:
                logger.error("Binance 24hr ticker failed for %s: %s", sym, e)

        snapshot.klines.extend(binance_klines)
        meta_list.append(binance_meta)

        # ── 2. CoinGecko OHLC + market overview ──────────────────
        cg_meta = SourceMetadata(source="coingecko", status="ok")
        coin_map = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum"}
        for sym, coin_id in coin_map.items():
            try:
                klines = self.coingecko.get_klines(coin_id=coin_id, days=7)
                cg_meta.klines_count += len(klines)
                snapshot.klines.extend(k.to_dict() for k in klines)
            except Exception as e:
                logger.error("CoinGecko OHLC failed for %s: %s", sym, e)
                cg_meta.status = "error"
                cg_meta.error_message = str(e)

        try:
            overview_items = self.coingecko.get_market_overview(per_page=10)
            cg_meta.overview_count = len(overview_items)
            snapshot.market_overview.extend(item.to_dict() for item in overview_items)
        except Exception as e:
            logger.error("CoinGecko market overview failed: %s", e)
            cg_meta.status = "error"

        meta_list.append(cg_meta)

        # ── 3. News — 双路采集: 加密新闻 + 中文财经新闻 ────────
        news_meta = SourceMetadata(source="aggregated", status="ok")

        # 3a. 加密新闻 (CoinGecko / CryptoPanic)
        try:
            crypto_news = self.news.fetch_all(hours=24, limit=20)
            news_meta.news_count += len(crypto_news)
            snapshot.news.extend(item.to_dict() for item in crypto_news)
            logger.info("加密新闻: %d 条 (CoinGecko/CryptoPanic)", len(crypto_news))
        except Exception as e:
            logger.error("加密新闻采集失败: %s", e)
            news_meta.status = "error"
            news_meta.error_message = str(e)

        # 3b. 中文财经新闻 (AKShare → Tushare → RSSHub → 缓存兜底)
        multi_meta = SourceMetadata(source="multi_source_cn", status="ok")
        try:
            cn_news = self.multi_news.fetch_all()
            if cn_news == "missing":
                multi_meta.status = "missing"
                multi_meta.error_message = "全部中文新闻源失效且无缓存 (AKShare/Tushare/RSSHub/缓存)"
                logger.warning("中文新闻采集: 全部数据源失效，标记为 missing")
            elif isinstance(cn_news, list):
                if cn_news and len(cn_news) > 0 and cn_news[0].get("status") == "fallback":
                    multi_meta.status = "fallback"
                    multi_meta.error_message = "公网源失效，使用内置测试数据"
                    logger.warning("中文新闻: 使用内置测试数据 (公网源全部不可用)")
                multi_meta.news_count = len(cn_news)
                snapshot.news.extend(cn_news)
                logger.info("中文新闻: %d 条 (AKShare/Tushare/RSSHub/缓存/内置)", len(cn_news))
        except Exception as e:
            logger.error("中文新闻采集失败: %s", e)
            multi_meta.status = "error"
            multi_meta.error_message = str(e)
        meta_list.append(multi_meta)

        meta_list.append(news_meta)

        # ── 4. X/Twitter ─────────────────────────────────────────
        x_meta = SourceMetadata(source="x_twitter", status="missing_config")
        try:
            x_items = self.xwatch.fetch_recent(count=4)
            x_meta.news_count = len(x_items)
            snapshot.news.extend(item.to_dict() for item in x_items)
        except Exception as e:
            logger.error("X watchlist fetch failed: %s", e)
            x_meta.status = "error"
            x_meta.error_message = str(e)
        meta_list.append(x_meta)

        # ── Finalize ─────────────────────────────────────────────
        snapshot.source_metadata = [m.to_dict() for m in meta_list]
        self._write(snapshot)
        logger.info(
            "Snapshot written: %d klines, %d overview items, %d news items",
            len(snapshot.klines),
            len(snapshot.market_overview),
            len(snapshot.news),
        )
        return snapshot

    def _write(self, snapshot: MarketSnapshot) -> Path:
        """Write snapshot JSON atomically."""
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(snapshot.to_json())
        logger.info("Saved to %s", SNAPSHOT_PATH)
        return SNAPSHOT_PATH
