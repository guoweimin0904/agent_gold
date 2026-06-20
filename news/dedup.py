"""Deduplication engine — content-hash based, with cross-source mention tracking."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from news.schemas import DedupState, NewsAnalystReport, RawNews

logger = logging.getLogger("news.dedup")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEEN_DB_PATH = DATA_DIR / "seen_news.json"


class DedupEngine:
    """
    Content-hash deduplication with multi-source tracking.

    Two news items are "the same" if their MD5(content) matches.
    DedupState tracks how many sources and which ones have covered it.
    """

    def __init__(self, window_hours: int = 72) -> None:
        self.window_hours = window_hours
        self._db: dict[str, dict[str, Any]] = self._load_db()

    # ── Main check ──────────────────────────────────────────────────

    def check(self, raw: RawNews) -> DedupState:
        """Check a raw item against the seen DB. Returns dedup state."""
        content_hash = self._content_hash(raw)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self.window_hours)

        # Prune old entries
        stale_keys = [
            k for k, v in self._db.items()
            if datetime.fromisoformat(v.get("first_seen", "2000")).replace(
                tzinfo=timezone.utc
            ) < cutoff
        ]
        for k in stale_keys:
            del self._db[k]

        if content_hash in self._db:
            entry = self._db[content_hash]
            new_sources = entry["sources"]
            if raw.source not in new_sources:
                new_sources.append(raw.source)
            state = DedupState(
                is_duplicate=True,
                duplicate_of_id=content_hash,
                first_seen_at=entry["first_seen"],
                mention_count=len(new_sources),
                sources=list(new_sources),
            )
        else:
            state = DedupState(
                is_duplicate=False,
                sources=[raw.source],
            )
            self._db[content_hash] = {
                "first_seen": now.isoformat(),
                "sources": [raw.source],
            }

        self._save_db()
        return state

    def mark_seen(self, report: NewsAnalystReport) -> None:
        """Record a processed report in the seen DB."""
        if report.news_id and report.news_id not in self._db:
            self._db[report.news_id] = {
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "sources": [report.source],
            }
            self._save_db()

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _content_hash(raw: RawNews) -> str:
        """MD5 of title + first 300 chars of body."""
        content = f"{raw.title.strip()}|{raw.body.strip()[:300]}"
        return hashlib.md5(content.encode()).hexdigest()

    def _load_db(self) -> dict[str, dict[str, Any]]:
        if SEEN_DB_PATH.exists():
            try:
                return json.loads(SEEN_DB_PATH.read_text())
            except Exception:
                logger.warning("Failed to load seen_news.json, starting fresh")
        return {}

    def _save_db(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SEEN_DB_PATH.write_text(
            json.dumps(self._db, indent=2, ensure_ascii=False)
        )
