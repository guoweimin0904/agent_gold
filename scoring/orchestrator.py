"""Scoring orchestrator — runs all 7 scorers, aggregates, applies veto, outputs report.

Veto logic:
  - Kill switch active → veto all
  - Daily loss limit hit → veto
  - Validator agent disapproves veto-level violations → veto
  - S-level event + risk_pause → auto-veto (unless confirmed by human)

Aggregation:
  raw_total = Σ sub_scores  (max 600)
  final_score = (raw_total - risk_deduction) / 6  (normalised to 0-100)
"""

import json
import logging
from pathlib import Path
from typing import Any

from scoring.schemas import ScoringReport, SubScores, VetoInfo
from scoring.scorers import (
    score_backtest,
    score_event,
    score_fund_flow,
    score_kline,
    score_risk,
    score_sentiment,
    score_technical,
)

logger = logging.getLogger("scoring.orchestrator")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "scoring_report.json"


class ScoringOrchestrator:
    """
    Full scoring pipeline: fetch context → run 7 scorers → aggregate → veto → output.

    Usage:
        report = ScoringOrchestrator().score(symbol="BTCUSDT")
        print(report.to_json())
    """

    def __init__(self) -> None:
        self._veto_override: VetoInfo | None = None

    # ── Public API ──────────────────────────────────────────────────

    def score(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        market: str = "crypto",
        # Context (injected externally or from data_layer/backtest/news)
        klines: list[dict[str, Any]] | None = None,
        latest_indicators: dict[str, Any] | None = None,
        market_overview: list[dict[str, Any]] | None = None,
        news_report: dict[str, Any] | None = None,
        backtest_result: dict[str, Any] | None = None,
        risk_status: dict[str, Any] | None = None,
        # External veto
        validator_veto: str | None = None,
        risk_veto: str | None = None,
    ) -> ScoringReport:
        """
        Run the full scoring pipeline.

        Parameters
        ----------
        validator_veto : str | None
            If set (non-empty), the validator agent has vetoed. Reason string.
        risk_veto : str | None
            If set, the risk control layer has vetoed. Reason string.
        """
        logger.info("Scoring %s (%s) — running 7 scorers", symbol, timeframe)

        # ── 1. Run sub-scorers ───────────────────────────────────
        dim_event = score_event(news_report)
        dim_sentiment = score_sentiment(news_report, market_overview)
        dim_kline = score_kline(klines)
        dim_technical = score_technical(latest_indicators)
        dim_fund = score_fund_flow(market_overview, symbol)
        dim_backtest = score_backtest(backtest_result)
        dim_risk = score_risk(risk_status)

        dimensions = [
            dim_event, dim_sentiment, dim_kline,
            dim_technical, dim_fund, dim_backtest, dim_risk,
        ]

        # ── 2. Aggregate ─────────────────────────────────────────
        sub = SubScores(
            event_score=dim_event.score,
            sentiment_score=dim_sentiment.score,
            kline_score=dim_kline.score,
            technical_score=dim_technical.score,
            fund_flow_score=dim_fund.score,
            backtest_score=dim_backtest.score,
            risk_deduction=dim_risk.score,
        )
        raw = sub.raw_total
        deduction = sub.risk_deduction
        final_score = max(0, min(100, (raw - deduction) / 6))

        # ── 3. Veto logic ────────────────────────────────────────
        veto = VetoInfo(vetoed=False)

        # External veto: validator agent
        if validator_veto:
            veto.vetoed = True
            veto.vetoed_by = "validator_agent"
            veto.reason = validator_veto

        # External veto: risk control
        if risk_veto:
            veto.vetoed = True
            veto.vetoed_by = "risk_control"
            veto.reason = risk_veto

        # Auto-veto: kill switch
        if risk_status and risk_status.get("kill_switch_active", False):
            veto.vetoed = True
            veto.vetoed_by = "kill_switch"
            veto.reason = "杀开关已激活，禁止所有交易"

        # Auto-veto: S-level event + risk_pause (unless overridden)
        if risk_status and risk_status.get("s_event_active", False):
            if not veto.vetoed:
                veto.vetoed = True
                veto.vetoed_by = "risk_control"
                veto.reason = "S级事件触发风险暂停，自动否决"
                final_score = min(final_score, 40)  # clamp low

        # ── 4. Build report ──────────────────────────────────────
        report = ScoringReport(
            market=market,  # type: ignore
            symbol=symbol,
            timeframe=timeframe,
            scores=sub,
            dimensions=[d.__dict__ for d in dimensions],
            final_score=round(final_score, 1),
            veto=veto,
        )
        report.update_decision()

        # ── 5. Save ──────────────────────────────────────────────
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report.to_json())
        logger.info("Scoring report saved to %s", REPORT_PATH)

        self._print_summary(report)
        return report

    def set_veto(self, veto: VetoInfo) -> None:
        """Override veto state (for external injection)."""
        self._veto_override = veto

    @staticmethod
    def _print_summary(report: ScoringReport) -> None:
        print("\n─── 评分报告 ───")
        print(f"标的: {report.symbol} ({report.timeframe})")
        print(f"子分: event={report.scores.event_score:.0f}  sentiment={report.scores.sentiment_score:.0f}  "
              f"kline={report.scores.kline_score:.0f}  tech={report.scores.technical_score:.0f}  "
              f"fund={report.scores.fund_flow_score:.0f}  bt={report.scores.backtest_score:.0f}")
        print(f"风险扣除: -{report.scores.risk_deduction:.0f}")
        print(f"总分: {report.final_score:.1f}")
        print(f"决策: {report.decision}")
        if report.veto.vetoed:
            print(f"🛑 已被 {report.veto.vetoed_by} 否决: {report.veto.reason}")
        print(f"需要人工确认: {report.need_human_confirm}")
        print(report.disclaimer())
