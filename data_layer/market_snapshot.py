"""Market snapshot data model — the single output contract for data_layer."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class SourceMetadata:
    """Per-source fetch status."""
    source: str           # "binance" | "coingecko" | "cryptopanic" | "x_twitter"
    status: str           # "ok" | "error" | "missing_config"
    klines_count: int = 0
    overview_count: int = 0
    news_count: int = 0
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketSnapshot:
    """Top-level snapshot document."""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    klines: list[dict[str, Any]] = field(default_factory=list)
    market_overview: list[dict[str, Any]] = field(default_factory=list)
    news: list[dict[str, Any]] = field(default_factory=list)
    source_metadata: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
