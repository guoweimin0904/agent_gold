"""Opportunity schemas — output model for all 7 opportunity types + resonance.

Each scanner produces one OpportunitySignal.
The resonance detector produces ResonanceSignal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

SignalType = Literal[
    "listing", "blackswan", "extreme_sentiment", "breakout",
    "fund_flow", "policy", "earnings", "resonance",
]

Priority = Literal["critical", "high", "medium", "low", "info"]


@dataclass
class ScannerMetadata:
    """Metadata from the scanner that produced this signal."""
    scanner: str
    scanned_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data_available: bool = True
    data_missing: bool = False


@dataclass
class OpportunitySignal:
    """
    A single opportunity signal from one scanner.

    Each scanner type has its own score fields, but all share this base.
    """
    signal_type: SignalType = "listing"
    symbol: str = ""
    priority: Priority = "low"

    # ── Common scores ──
    score: float = 0.0                # 0-100 overall score for this type
    confidence: float = 0.0           # 0.0-1.0

    # ── Type-specific scores ──
    # Listing
    event_score: float = 0.0
    already_pumped: float = 0.0      # 0.0-1.0 how much price has already moved
    trade_window: str = ""           # e.g. "1-3h before listing"
    # Blackswan
    risk_level: str = "low"
    panic_probability: float = 0.0   # 0.0-1.0
    risk_pause: bool = False
    # Extreme sentiment
    sentiment_score: float = 0.0
    is_extreme: bool = False
    contrarian_signal: bool = False
    # Breakout
    kline_score: float = 0.0
    breakout: bool = False
    volume_confirmed: bool = False
    # Fund flow
    fund_flow_score: float = 0.0
    trend_support: float = 0.0       # 0.0-1.0
    # Policy
    policy_score: float = 0.0
    benefit_sector: str = ""
    risk_note: str = ""
    # Earnings
    earnings_surprise: float = 0.0
    risk_flag: bool = False

    # ── Metadata ──
    summary: str = ""
    scanner_meta: ScannerMetadata = field(default_factory=ScannerMetadata)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scanner_meta"] = asdict(self.scanner_meta)
        return d


@dataclass
class ResonanceSignal:
    """
    Policy + fund flow resonance — when both agree.

    This is the strongest candidate filter.
    """
    symbol: str = ""
    policy_score: float = 0.0
    fund_flow_score: float = 0.0
    final_score: float = 0.0
    signal_strength: float = 0.0     # 0.0-1.0
    candidate: bool = False
    benefit_sector: str = ""
    summary: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpportunityBatch:
    """
    Top-level output from OpportunityOrchestrator.
    Contains all scanned signals + resonance candidates.
    """
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    total_signals: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    signals: list[dict[str, Any]] = field(default_factory=list)
    resonance_signals: list[dict[str, Any]] = field(default_factory=list)
    best_candidate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
