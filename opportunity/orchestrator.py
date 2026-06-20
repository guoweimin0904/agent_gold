"""Opportunity orchestrator — runs all 7 scanners + resonance detector, aggregates.

Output: OpportunityBatch with ranked signals + best candidate.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from opportunity.resonance import ResonanceDetector
from opportunity.scanners_event import scan_blackswan, scan_extreme_sentiment, scan_listing
from opportunity.scanners_fundamental import scan_earnings, scan_policy
from opportunity.scanners_technical import scan_breakout, scan_fund_flow
from opportunity.schemas import OpportunityBatch, OpportunitySignal, ResonanceSignal

logger = logging.getLogger("opportunity.orchestrator")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUTPUT_PATH = DATA_DIR / "opportunity_batch.json"


class OpportunityOrchestrator:
    """
    Run all 7 scanners + resonance detector.

    Usage:
        batch = OpportunityOrchestrator().scan_all(symbol="BTCUSDT", context=...)
    """

    def __init__(self) -> None:
        self.resonance = ResonanceDetector()

    def scan_all(
        self,
        symbol: str = "BTCUSDT",
        # Context — each scanner uses what it needs
        exchange_announcements: list[dict[str, Any]] | None = None,
        news_report: dict[str, Any] | None = None,
        risk_status: dict[str, Any] | None = None,
        klines: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
        market_overview: list[dict[str, Any]] | None = None,
        policy_report: dict[str, Any] | None = None,
        earnings_data: list[dict[str, Any]] | None = None,
        corporate_events: list[dict[str, Any]] | None = None,
        sentiment_score: float = 50.0,
        price_change_24h_pct: float = 0.0,
        price_change_7d_pct: float = 0.0,
        price_drop_24h_pct: float = 0.0,
    ) -> OpportunityBatch:
        """Run all scanners and resonance detection."""
        logger.info("Opportunity scan for %s", symbol)

        signals: list[OpportunitySignal] = []

        # ── 1. 交易所上币 ───────────────────────────────────────────
        s_listing = scan_listing(
            symbol, exchange_announcements, price_change_24h_pct,
        )
        signals.append(s_listing)

        # ── 2. 黑天鹅 ───────────────────────────────────────────────
        s_blackswan = scan_blackswan(symbol, news_report, risk_status, price_drop_24h_pct)
        signals.append(s_blackswan)

        # ── 3. 情绪极端 ─────────────────────────────────────────────
        rsi = (indicators or {}).get("rsi", 50)
        s_extreme = scan_extreme_sentiment(
            symbol, sentiment_score, rsi, price_change_24h_pct, price_change_7d_pct,
        )
        signals.append(s_extreme)

        # ── 4. 突破行情 ─────────────────────────────────────────────
        s_breakout = scan_breakout(symbol, klines, indicators)
        signals.append(s_breakout)

        # ── 5. 资金驱动 ─────────────────────────────────────────────
        s_fund = scan_fund_flow(symbol, market_overview, klines)
        signals.append(s_fund)

        # ── 6. 政策驱动 ─────────────────────────────────────────────
        s_policy = scan_policy(symbol, policy_report)
        signals.append(s_policy)

        # ── 7. 业绩/公告 ────────────────────────────────────────────
        s_earnings = scan_earnings(symbol, earnings_data, corporate_events)
        signals.append(s_earnings)

        # ── Resonance: 政策+资金 ────────────────────────────────────
        resonance = self.resonance.detect(
            symbol, s_policy.to_dict(), s_fund.to_dict(),
        )

        # ── Aggregate ───────────────────────────────────────────────
        critical = [s for s in signals if s.priority == "critical"]
        high = [s for s in signals if s.priority == "high"]
        medium = [s for s in signals if s.priority == "medium"]
        low = [s for s in signals if s.priority == "low"]

        # Find best candidate: highest score among high priority + non-risk
        all_candidates = [s for s in signals if s.priority in ("high", "critical") and s.score >= 60]
        all_candidates.sort(key=lambda s: s.score, reverse=True)
        best = None
        if all_candidates:
            best = all_candidates[0]
        elif resonance.candidate:
            # If no high-priority signal but resonance says yes
            best = type("obj", (object,), {
                "signal_type": "resonance", "symbol": symbol,
                "score": resonance.final_score, "priority": "high",
                "summary": resonance.summary,
            })()

        batch = OpportunityBatch(
            total_signals=len(signals),
            critical_count=len(critical),
            high_count=len(high),
            medium_count=len(medium),
            low_count=len(low),
            signals=[s.to_dict() for s in signals],
            resonance_signals=[resonance.to_dict()],
            best_candidate={
                "type": resonance.candidate and not all_candidates and "resonance" or (best and best.signal_type),
                "symbol": symbol,
                "score": round(best.score, 1) if best else 0,
                "priority": best.priority if best else "none",
                "summary": best.summary if best else "无强候选",
            } if best or resonance.candidate else None,
        )

        # ── Save ────────────────────────────────────────────────────
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(batch.to_json())
        logger.info("Opportunity batch saved to %s", OUTPUT_PATH)

        self._print(batch)
        return batch

    @staticmethod
    def _print(batch: OpportunityBatch) -> None:
        print(f"\n─── 机会扫描报告: {batch.total_signals} signals ───")
        print(f"  🔴 Critical: {batch.critical_count} | 🟠 High: {batch.high_count} | "
              f"🟡 Medium: {batch.medium_count} | ⚪ Low: {batch.low_count}")
        if batch.best_candidate:
            bc = batch.best_candidate
            print(f"  🏆 最佳候选: [{bc['type']}] {bc['symbol']} — score={bc['score']} | {bc.get('summary','')[:60]}")
        print()
        for sig in batch.signals:
            meta = sig.get("scanner_meta", {})
            s = "🛑" if sig.get("risk_pause") else \
                "🔴" if sig.get("priority") == "critical" else \
                "🟠" if sig.get("priority") == "high" else \
                "🟡" if sig.get("priority") == "medium" else "⚪"
            print(f"  {s} [{sig['signal_type']:18s}] score={sig['score']:5.1f} | {sig.get('summary','')[:70]}")
        print()
        for rs in batch.resonance_signals:
            c = "🔴" if rs.get("candidate") else "⚪"
            print(f"  {c} [共振] policy={rs.get('policy_score'):.0f} fund={rs.get('fund_flow_score'):.0f} "
                  f"strength={rs.get('signal_strength'):.0%} | {rs.get('summary','')[:60]}")
