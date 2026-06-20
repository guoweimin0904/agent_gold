"""X/Twitter watchlist — read-only monitoring with real missing/disabled states."""

import logging
from datetime import datetime, timezone
from typing import Any

from connectors.base import NewsItem

logger = logging.getLogger("connectors.xwatchlist")


class XWatchlistData:
    """Read-only X/Twitter watchlist monitor.

    NOTE: Requires X API v2 credentials (bearer token) to operate.
    Without credentials, all calls return missing-marked items.
    """

    def __init__(self, bearer_token: str | None = None) -> None:
        self.bearer_token = bearer_token
        self.accounts = [
            "cz_binance",
            "saylor",
            "VitalikButerin",
            "ai_9684xtpa",
        ]
        if not self.bearer_token:
            logger.warning(
                "X API bearer token not configured — "
                "all X watchlist data will be marked 'missing'"
            )

    def fetch_recent(self, count: int = 10) -> list[NewsItem]:
        """
        Fetch recent tweets from watchlist accounts.
        Without bearer token, returns missing-marked items.
        """
        if not self.bearer_token:
            return [self._missing_item(acct) for acct in self.accounts[:count]]

        # ── Real X API v2 call (requires paid X API access) ────────
        # TODO: implement with requests to api.twitter.com/2/tweets
        # Currently stubbed as missing since no token is present
        logger.info("X API available but endpoint not yet implemented")
        return [self._missing_item(acct) for acct in self.accounts[:count]]

    @staticmethod
    def _missing_item(account: str) -> NewsItem:
        return NewsItem(
            title="",
            url=f"https://x.com/{account}",
            published_at=datetime.now(timezone.utc).isoformat(),
            source="x_twitter",
            status="missing",
            summary=f"X API not configured — cannot fetch @{account} tweets",
        )
