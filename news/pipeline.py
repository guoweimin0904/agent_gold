"""News monitoring pipeline — orchestrates fetch → dedup → classify → enrich → output.

The pipeline reads from connectors (news_source, x_watchlist), runs each item through
deduplication, classification, and grading, then produces a NewsBatchReport.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from connectors.news_source import NewsData as RawNewsConnector
from connectors.x_watchlist import XWatchlistData
from news.classifier import NewsClassifier
from news.dedup import DedupEngine
from news.schemas import (
    Direction,
    NewsAnalystReport,
    NewsBatchReport,
    RawNews,
)

logger = logging.getLogger("news.pipeline")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "news_report.json"


class NewsPipeline:
    """
    End-to-end news pipeline: fetch → dedup → classify → grade → output.

    Usage:
        pipeline = NewsPipeline()
        batch = pipeline.run(hours=24)
    """

    def __init__(self) -> None:
        self.raw_connector = RawNewsConnector()
        self.x_connector = XWatchlistData()
        self.classifier = NewsClassifier()
        self.dedup = DedupEngine(window_hours=72)

    # ── Public API ──────────────────────────────────────────────────

    def run(
        self,
        hours: int = 24,
        max_items: int = 30,
    ) -> NewsBatchReport:
        """
        Run the full pipeline.

        Parameters
        ----------
        hours : int
            Look-back window in hours.
        max_items : int
            Maximum items to process.

        Returns
        -------
        NewsBatchReport
        """
        logger.info("Starting news pipeline (window=%dh, max=%d)", hours, max_items)

        # ── 1. Fetch from all sources ───────────────────────────
        raw_items: list[RawNews] = []
        duplicates_removed = 0

        # CoinGecko / CryptoPanic news
        try:
            fetched = self.raw_connector.fetch_all(hours=hours, limit=max_items)
            for item in fetched:
                raw = RawNews(
                    title=item.title,
                    body=item.summary,
                    url=item.url,
                    source=item.source,
                    published_at=item.published_at,
                    source_type="news",
                )
                raw_items.append(raw)
        except Exception as e:
            logger.error("News connector fetch failed: %s", e)

        # X/Twitter watchlist
        try:
            x_items = self.x_connector.fetch_recent(count=5)
            for item in x_items:
                if item.status == "missing":
                    continue
                raw = RawNews(
                    title=item.title,
                    body=item.summary,
                    url=item.url,
                    source="x_twitter",
                    published_at=item.published_at,
                    source_type="social",
                )
                raw_items.append(raw)
        except Exception as e:
            logger.warning("X watchlist fetch failed: %s", e)

        logger.info("Fetched %d raw items", len(raw_items))

        if not raw_items:
            return self._empty_batch(hours)

        # ── 2. Dedup + classify ─────────────────────────────────
        reports: list[NewsAnalystReport] = []
        for raw in raw_items:
            # Dedup
            dedup_state = self.dedup.check(raw)
            if dedup_state.is_duplicate:
                duplicates_removed += 1
                # But still classify if multi-source (重大新闻至少两个来源)
                if dedup_state.mention_count < 2:
                    continue

            # Classify
            report = self.classifier.classify(raw)
            report.dedup = dedup_state
            reports.append(report)
            self.dedup.mark_seen(report)

        logger.info(
            "Processed %d → %d reports (removed %d dupes)",
            len(raw_items), len(reports), duplicates_removed,
        )

        # ── 3. Build batch report ───────────────────────────────
        s_count = sum(1 for r in reports if r.impact_level == "S")
        a_count = sum(1 for r in reports if r.impact_level == "A")
        b_count = sum(1 for r in reports if r.impact_level == "B")
        c_count = sum(1 for r in reports if r.impact_level == "C")
        risk_pause = s_count > 0
        overall_bias = self._aggregate_bias(reports)

        batch = NewsBatchReport(
            window_hours=hours,
            total_raw=len(raw_items),
            duplicates_removed=duplicates_removed,
            reports=[r.to_dict() for r in reports],
            s_events=s_count,
            a_events=a_count,
            b_events=b_count,
            c_events=c_count,
            risk_paused_suggested=risk_pause,
            overall_bias=overall_bias,
        )

        # ── 4. Write to disk ────────────────────────────────────
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(batch.to_json())
        logger.info("News report saved to %s", REPORT_PATH)

        # Print summary
        self._print_summary(batch)

        return batch

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_bias(reports: list[NewsAnalystReport]) -> Direction:
        bullish = sum(1 for r in reports if r.direction == "bullish")
        bearish = sum(1 for r in reports if r.direction == "bearish")
        if bullish > bearish and bullish >= 3:
            return "bullish"
        if bearish > bullish and bearish >= 3:
            return "bearish"
        if bullish == bearish and bullish > 0:
            return "mixed"
        return "neutral"

    @staticmethod
    def _empty_batch(hours: int) -> NewsBatchReport:
        batch = NewsBatchReport(window_hours=hours)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(batch.to_json())
        return batch

    @staticmethod
    def _print_summary(batch: NewsBatchReport) -> None:
        print("\n─── 新闻监控报告 ───")
        print(f"窗口: {batch.window_hours}h | 原始: {batch.total_raw} | 去重: {batch.duplicates_removed}")
        print(f"S级: {batch.s_events} | A级: {batch.a_events} | B级: {batch.b_events} | C级: {batch.c_events}")
        print(f"总体偏向: {batch.overall_bias} | 建议风险暂停: {batch.risk_paused_suggested}")
        if batch.reports:
            print(f"\n── 分级明细 ──")
            for r in batch.reports:
                level = r.get("impact_level", "C")
                dir_ = r.get("direction", "neutral")
                truth = r.get("truth_status", "unverified")
                pause = "🛑" if r.get("risk_pause") else "  "
                title = r.get("title", "")[:60]
                cred = r.get("credibility", 0)
                print(f"  {pause}[{level}] {dir_:>8s} | 可信度{cred:.0%} | {truth:20s} | {title}")
        print()
        print(NewsAnalystReport.disclaimer())
