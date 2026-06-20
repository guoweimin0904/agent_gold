"""Output data models for the news monitoring pipeline.

Every news article goes through dedup → summarise → classify → enrich,
and produces a single NewsAnalystReport.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

# ── Typed enums ─────────────────────────────────────────────────────

Direction = Literal["bullish", "bearish", "neutral", "mixed"]
ImpactLevel = Literal["S", "A", "B", "C"]       # S = critical, C = noise
TruthStatus = Literal["verified", "unverified", "rumour", "confirmed_official", "multiple_sources"]


# ── Raw input canonical form ────────────────────────────────────────

@dataclass
class RawNews:
    """Canonical raw news item before processing."""
    id: str = ""                            # content-hash or source id
    title: str = ""
    body: str = ""
    url: str = ""
    source: str = ""                        # "cryptopanic" | "x_twitter" | "coingecko_news"
    author: str = ""                        # handle or publication name
    published_at: str = ""                  # ISO-8601
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_type: str = ""                   # "news" | "social" | "announcement" | "macro"
    tags: list[str] = field(default_factory=list)


# ── Dedup state ─────────────────────────────────────────────────────

@dataclass
class DedupState:
    """Result of deduplication against the seen-news DB."""
    is_duplicate: bool = False
    duplicate_of_id: str = ""
    first_seen_at: str = ""
    mention_count: int = 1                   # how many sources carried this
    sources: list[str] = field(default_factory=list)  # source names


# ── The final report ────────────────────────────────────────────────

@dataclass
class NewsAnalystReport:
    """
    Single processed news item — the unified output of the news pipeline.

    Fields match the requirements exactly.
    """
    # ── Identity ──
    news_id: str = ""
    title: str = ""
    url: str = ""

    # ── Summarisation ──
    summary: str = ""                         # 1-2 sentence LLM / rule summary

    # ── Market relevance ──
    related_symbols: list[str] = field(default_factory=list)
    direction: Direction = "neutral"          # never directly "title利好=上涨"
    impact_level: ImpactLevel = "C"           # default noise; S = risk_pause

    # ── Credibility & verification ──
    credibility: float = 0.3                  # 0.0-1.0; default low
    truth_status: TruthStatus = "unverified"  # rumour/KOL → unverified
    already_priced: float = 0.0               # 0.0-1.0 how much market has priced in

    # ── Risk control ──
    risk_pause: bool = False                  # S级事件必须 True
    risk_note: str = ""                       # explanation for risk_pause / caution
    risk_level: str = "low"                   # "low" | "medium" | "high" | "critical"

    # ── Provenance ──
    source: str = ""
    published_at: str = ""
    source_type: str = ""
    dedup: DedupState = field(default_factory=DedupState)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["dedup"] = asdict(self.dedup)
        return d

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 新闻分析仅用于研究参考。标题不能等同于价格上涨。"
            "所有涉及市场方向的判断均附带概率性和时效性约束。"
        )


# ── Batch output ────────────────────────────────────────────────────

@dataclass
class NewsBatchReport:
    """Batch of processed news with overall market sentiment snapshot."""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    window_hours: int = 24
    total_raw: int = 0
    duplicates_removed: int = 0
    reports: list[dict[str, Any]] = field(default_factory=list)

    # Aggregate signals
    s_events: int = 0
    a_events: int = 0
    b_events: int = 0
    c_events: int = 0
    risk_paused_suggested: bool = False
    overall_bias: Direction = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
