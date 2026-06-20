"""Event classifier — impact level grading, credibility scoring, truth status inference.

No "标题利好 = 上涨" logic. All grading is based on source type, author authority,
multi-source confirmation, and event nature.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from news.schemas import (
    DedupState,
    Direction,
    ImpactLevel,
    NewsAnalystReport,
    RawNews,
    TruthStatus,
)

logger = logging.getLogger("news.classifier")

# ── Authority / source scoring ──────────────────────────────────────

OFFICIAL_DOMAINS = {
    "sec.gov", "federalreserve.gov", "bls.gov", "treasury.gov",
    "binance.com", "binance.us", "coinbase.com", "coinbase.blog",
    "ethereum.org", "bitcoin.org", "whitehouse.gov",
}

KNOWN_KOL_HANDLES = {
    "cz_binance", "saylor", "VitalikButerin", "elonmusk",
}

HIGH_AUTHORITY = {
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
    "coindesk.com", "theblock.co", "cointelegraph.com",
}


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    m = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
    return m.group(1).lower() if m else ""


def _source_authority_score(source: str, url: str, author: str) -> float:
    """Score source authority 0.0-1.0."""
    domain = _extract_domain(url)

    if domain in OFFICIAL_DOMAINS:
        return 1.0
    if domain in HIGH_AUTHORITY:
        return 0.8
    if source == "x_twitter" and author in KNOWN_KOL_HANDLES:
        return 0.4  # KOLs are influential but not authoritative
    if source == "x_twitter":
        return 0.1
    return 0.3  # generic news aggregator


# ── Impact level determination ──────────────────────────────────────

# Keywords that strongly suggest S/A level events
S_LEVEL_PATTERNS = [
    r"(?:SEC|CFTC|DOJ|FBI|Treasury)\s+(?:sue|charges|files|investigat|indict|penalty)",
    r"(?:exchange|platform)\s+(?:hack|exploit|drain|theft)(?:\s+(?:over|of|amounting\s+to))?\s*(?:\$)?\d+[mkb]?",
    r"(?:stablecoin\s+depeg|depeg\s+event)",
    r"(?:bankruptcy|insolvency|suspend|freeze)\s+(?:withdrawals?|all\s+trading)",
    r"executive\s+order.*(?:crypto|digital\s+asset)",
    r"market-wide\s+(?:liquidation|cascade|crash)",
    r"major\s+(?:protocol|chain|exchange|platform)\s+(?:exploit|compromise|hack|breach)",
]

A_LEVEL_PATTERNS = [
    r"(?:rate\s+decision|interest\s+rate|fed\s+(?:hike|cut|pause))",
    r"(?:CPI|PPI|NFP|employment|inflation)\s+(?:data|report|release)",
    r"(?:partnership|integration|listing)\s+(?:with|on)\s+(?:coinbase|binance|major)",
    r"(?:ETF|ETP)\s+(?:approval|rejection|filing|launch)",
    r"(?:halving|fork|upgrade)\s+(?:completed|scheduled|activated)",
    r"regulatory\s+(?:framework|bill|law|clarity)",
    r"(?:whale|large\s+wallet|institutional)\s+(?:movement|accumulation|transfer)",
]

B_LEVEL_PATTERNS = [
    r"(?:upgrade|v\d+)\s+(?:deployed|live|mainnet)",
    r"(?:TVL|tvl)\s+(?:hits|reaches|ATH|新高)",
    r"(?:token\s+buyback|burn|supply\s+reduction)",
    r"(?:layer\s*2|L2)\s+(?:milestone|transaction|volume)",
    r"(?:cefi|defi)\s+(?:yield|apy|rate)\s+change",
]

# ── Direction inference (conservative) ──────────────────────────────

BULLISH_KEYWORDS = {
    "buy", "accumulate", "partnership", "adoption", "integration",
    "upgrade", "launch", "growth", "positive", "breakthrough",
    "approval", "institutional", "ATH",
}

BEARISH_KEYWORDS = {
    "sell", "dump", "liquidation", "crash", "hack", "exploit",
    "regulatory", "ban", "fraud", "scam", "decline", "investigation",
    "lawsuit", "penalty", "fine", "sanction", "withdrawal halt",
}

NEUTRAL_KEYWORDS = {
    "analysis", "report", "research", "survey", "update",
    "maintenance", "scheduled",
}


class NewsClassifier:
    """Classify a single news item into impact level, direction, and credibility."""

    def classify(self, raw: RawNews) -> NewsAnalystReport:
        """Full classification pipeline for one item."""
        title_lower = raw.title.lower()
        body_lower = raw.body.lower()
        combined = f"{title_lower} {body_lower}"
        domain = _extract_domain(raw.url)
        source = raw.source

        # ── 1. Dedup hash ───────────────────────────────────────
        content_hash = hashlib.md5(
            f"{raw.title}|{raw.body[:200]}".encode()
        ).hexdigest()
        news_id = content_hash

        # ── 2. Impact level ─────────────────────────────────────
        impact_level, impact_reason = self._grade_impact(combined, raw)

        # ── 3. Direction ────────────────────────────────────────
        direction = self._infer_direction(combined)
        if direction == "bullish":
            impact_reason += " | ⚠️ 标题利好 ≠ 价格上涨，仅指示相关事件方向"

        # ── 4. Truth status & credibility ───────────────────────
        truth_status, credibility = self._assess_truth(
            source, domain, raw.author, raw.url, combined
        )

        # ── 5. Already priced ───────────────────────────────────
        already_priced = self._estimate_priced_in(impact_level, source, raw.author)

        # ── 6. Risk pause ───────────────────────────────────────
        risk_pause = impact_level == "S"
        risk_level = self._risk_level(impact_level, credibility)
        risk_note_parts: list[str] = []
        if risk_pause:
            risk_note_parts.append("🛑 S级事件触发风险暂停")
        if truth_status == "unverified":
            risk_note_parts.append("信息来源未验证，请勿仅据此操作")
        if credibility < 0.3:
            risk_note_parts.append(f"可信度仅{credibility:.0%}，建议等待多方确认")
        if impact_reason:
            risk_note_parts.append(impact_reason)

        # ── 7. Related symbols ──────────────────────────────────
        related = self._extract_symbols(combined)

        # ── 8. Summary ──────────────────────────────────────────
        summary = self._generate_summary(raw, impact_level, direction, truth_status)

        return NewsAnalystReport(
            news_id=news_id,
            title=raw.title,
            url=raw.url,
            summary=summary,
            related_symbols=related,
            direction=direction,
            impact_level=impact_level,
            credibility=credibility,
            truth_status=truth_status,
            already_priced=already_priced,
            risk_pause=risk_pause,
            risk_note="; ".join(risk_note_parts),
            risk_level=risk_level,
            source=raw.source,
            published_at=raw.published_at,
            source_type=raw.source_type,
        )

    # ── Internal methods ────────────────────────────────────────────

    @staticmethod
    def _grade_impact(text: str, raw: RawNews) -> tuple[ImpactLevel, str]:
        """Grade S/A/B/C based on content patterns and source."""
        for pattern in S_LEVEL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return "S", f"匹配S级模式: {pattern}"

        for pattern in A_LEVEL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return "A", f"匹配A级模式: {pattern}"

        for pattern in B_LEVEL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return "B", f"匹配B级模式: {pattern}"

        # KOL tweets are at least B if above threshold
        if raw.source == "x_twitter" and raw.author in KNOWN_KOL_HANDLES:
            if any(w in text for w in BULLISH_KEYWORDS | BEARISH_KEYWORDS):
                return "B", f"KOL喊单（{raw.author}），权威性低，按B级处理"

        return "C", "常规内容，无显著市场影响信号"

    @staticmethod
    def _infer_direction(text: str) -> Direction:
        """
        Infer direction from content. Conservative: never maps directly to price.
        Returns "bullish"/"bearish" only for clear event-direction pairing.
        """
        bullish_count = sum(1 for w in BULLISH_KEYWORDS if w in text)
        bearish_count = sum(1 for w in BEARISH_KEYWORDS if w in text)
        neutral_count = sum(1 for w in NEUTRAL_KEYWORDS if w in text)

        if neutral_count > max(bullish_count, bearish_count):
            return "neutral"
        if bullish_count > bearish_count and bullish_count >= 2:
            return "bullish"  # multiple positive signals
        if bearish_count > bullish_count and bearish_count >= 2:
            return "bearish"
        if bullish_count == bearish_count and bullish_count > 0:
            return "mixed"
        return "neutral"

    @staticmethod
    def _assess_truth(
        source: str, domain: str, author: str, url: str, text: str
    ) -> tuple[TruthStatus, float]:
        """Assess truth status and assign credibility score 0.0-1.0."""
        # Official source
        if domain in OFFICIAL_DOMAINS:
            return "confirmed_official", 0.95

        # High-authority media
        if domain in HIGH_AUTHORITY:
            return "multiple_sources", 0.85

        # Crypto-native outlets
        crypto_outlets = {"coindesk.com", "theblock.co", "cointelegraph.com"}
        if domain in crypto_outlets:
            return "verified", 0.7

        # KOL tweet — always unverified
        if source == "x_twitter":
            if author in KNOWN_KOL_HANDLES:
                return "unverified", 0.35
            return "rumour", 0.1

        # Unknown aggregator — low confidence
        if "rumour" in text or "reportedly" in text or "sources say" in text:
            return "rumour", 0.2

        return "unverified", 0.3

    @staticmethod
    def _estimate_priced_in(level: ImpactLevel, source: str, author: str) -> float:
        """
        Estimate how much the market has already priced this event in.
        0.0 = completely unpriced (scoop), 1.0 = fully priced (old news).
        """
        if level == "S":
            return 0.1  # S events are usually shocks
        if level == "A":
            if source == "x_twitter":
                return 0.5  # KOL tweets get partially priced in fast
            return 0.3
        if level == "B":
            return 0.6
        return 0.8  # C-level = noise, likely already priced

    @staticmethod
    def _risk_level(impact: ImpactLevel, credibility: float) -> str:
        if impact == "S":
            return "critical"
        if impact == "A" and credibility < 0.5:
            return "high"
        if impact == "A":
            return "medium"
        return "low"

    @staticmethod
    def _extract_symbols(text: str) -> list[str]:
        """Extract likely crypto symbols from text."""
        symbols: list[str] = []
        # Common crypto names
        token_map = {
            "bitcoin": "BTC", "btc": "BTC", "ethereum": "ETH", "eth": "ETH",
            "solana": "SOL", "sol": "SOL", "binance coin": "BNB", "bnb": "BNB",
            "xrp": "XRP", "cardano": "ADA", "ada": "ADA",
            "dogecoin": "DOGE", "doge": "DOGE", "avalanche": "AVAX",
            "avax": "AVAX", "polkadot": "DOT", "dot": "DOT",
            "chainlink": "LINK", "link": "LINK",
        }
        text_lower = text.lower()
        for keyword, sym in token_map.items():
            if keyword in text_lower and sym not in symbols:
                symbols.append(sym)
        return symbols

    @staticmethod
    def _generate_summary(
        raw: RawNews, level: ImpactLevel, direction: Direction, truth: TruthStatus
    ) -> str:
        """Generate a 1-2 sentence summary."""
        parts = [raw.title]
        if level == "S":
            parts.append("[S级警报]")
        if truth in ("rumour", "unverified"):
            parts.append("[未经独立验证]")
        if direction == "neutral":
            pass  # no directional claim
        else:
            parts.append(f"[方向性: {direction}]")
        return " ".join(parts)
