"""Sentiment scoring — integrates with news classifier output.

No longer a standalone word-bag scorer. Delegates to the news pipeline
for classification and enriches with market context.
"""

import logging
from typing import Any

from news.classifier import NewsClassifier
from news.schemas import RawNews

logger = logging.getLogger("analysis.sentiment")


class SentimentScorer:
    """
    Sentiment scoring — wraps the news classifier for text-level scoring.

    This class exists for backward compatibility with existing code.
    New code should use news.pipeline.NewsPipeline directly.
    """

    def __init__(self) -> None:
        self.classifier = NewsClassifier()

    def score_text(self, text: str, source: str = "unknown") -> dict[str, Any]:
        """Score a single text string. Returns classifier fields."""
        raw = RawNews(
            title=text,
            body=text,
            source=source,
            source_type="news" if source != "x_twitter" else "social",
        )
        report = self.classifier.classify(raw)
        return {
            "direction": report.direction,
            "impact_level": report.impact_level,
            "credibility": report.credibility,
            "truth_status": report.truth_status,
            "risk_pause": report.risk_pause,
            "risk_note": report.risk_note,
            "summary": report.summary,
        }

    @staticmethod
    def aggregate_sentiment(scored_items: list[dict[str, Any]]) -> float:
        """Weighted average directional sentiment for a batch. -1.0 to +1.0."""
        direction_map = {"bullish": 1.0, "bearish": -1.0, "mixed": 0.0, "neutral": 0.0}
        total_weight = 0.0
        weighted_sum = 0.0
        for item in scored_items:
            direction = item.get("direction", "neutral")
            credibility = item.get("credibility", 0.3)
            base = direction_map.get(direction, 0.0)
            weighted_sum += base * credibility
            total_weight += credibility
        return weighted_sum / total_weight if total_weight > 0 else 0.0
