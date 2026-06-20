"""Event scoring — bridge between news pipeline and scoring engine.

DEPRECATED: New code should use scoring.orchestrator.ScoringOrchestrator directly.
This class is kept for backward compatibility and serves as an adapter.
"""

import logging
from typing import Any

from news.classifier import NewsClassifier
from news.schemas import RawNews

logger = logging.getLogger("analysis.event_scoring")


class EventScorer:
    """Evaluate market events and produce scores for the scoring engine.

    Returns dicts compatible with scoring.orchestrator's event_score input.
    """

    def __init__(self) -> None:
        self.classifier = NewsClassifier()

    def score_text(self, text: str, source: str = "unknown") -> dict[str, Any]:
        """Score a single text/caption for event impact."""
        raw = RawNews(title=text, body=text, source=source)
        report = self.classifier.classify(raw)
        return report.to_dict()

    def score_news_sentiment(
        self, news_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Process a batch of news items into scoring input format."""
        reports = []
        for item in news_items:
            title = item.get("title", "")
            body = item.get("body", title)
            raw = RawNews(
                title=title,
                body=body,
                url=item.get("url", ""),
                source=item.get("source", "unknown"),
                source_type=item.get("source_type", "news"),
            )
            reports.append(self.classifier.classify(raw).to_dict())
        return reports

    @staticmethod
    def build_news_report_for_scoring(
        classified_items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build the news_report dict that scoring.orchestrator expects."""
        return {"reports": classified_items}
