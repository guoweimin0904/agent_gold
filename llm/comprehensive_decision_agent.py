"""Comprehensive Decision Agent — fuses kline, news, scoring, backtest, risk into one decision.

Does NOT use LLM for inference (avoid latency, cost, hallucination).
Uses a deterministic rule engine + the scoring orchestrator output.

No "必涨", "梭哈", "稳赚" — ever.
"""

import json
import logging
from pathlib import Path
from typing import Any

from llm.decision_schemas import (
    ComprehensiveDecision,
    MarketState,
    resolve_direction,
)
from scoring.orchestrator import ScoringOrchestrator

logger = logging.getLogger("llm.comprehensive_agent")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DECISION_PATH = DATA_DIR / "comprehensive_decision.json"


class ComprehensiveDecisionAgent:
    """
    Comprehensive (deterministic) trading decision agent.

    Fuses:
      - market_snapshot.json  (klines, market_overview)
      - news_report.json      (news + classification)
      - scoring_report.json    (7-dimension scores)
      - backtest results       (win_rate, profit_factor, sample size)
      - risk status            (kill_switch, daily_loss, s_events)

    Output: ComprehensiveDecision with entry_condition, invalid_condition,
            stop_loss, take_profit — all in plain language.
    """

    def __init__(self) -> None:
        self._orchestrator = ScoringOrchestrator()

    # ── Public API ──────────────────────────────────────────────────

    def decide(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        market: str = "crypto",
        # Injected context
        klines: list[dict[str, Any]] | None = None,
        latest_indicators: dict[str, Any] | None = None,
        market_overview: list[dict[str, Any]] | None = None,
        news_report: dict[str, Any] | None = None,
        backtest_result: dict[str, Any] | None = None,
        risk_status: dict[str, Any] | None = None,
        validator_veto: str | None = None,
        risk_veto: str | None = None,
    ) -> ComprehensiveDecision:
        """
        Run full decision pipeline.

        1. Run scoring (all 7 sub-scorers)
        2. Determine market_state from klines
        3. Detect conflict signals
        4. Build entry/invalid/stop/take conditions
        5. Build position suggestion
        6. Apply veto
        7. Output
        """
        logger.info("Comprehensive decision for %s (%s)", symbol, timeframe)

        # ── 1. Run scoring ───────────────────────────────────────
        scoring_report = self._orchestrator.score(
            symbol=symbol,
            timeframe=timeframe,
            market=market,
            klines=klines,
            latest_indicators=latest_indicators,
            market_overview=market_overview,
            news_report=news_report,
            backtest_result=backtest_result,
            risk_status=risk_status,
            validator_veto=validator_veto,
            risk_veto=risk_veto,
        )

        fs = scoring_report.final_score
        vetoed = scoring_report.veto.vetoed
        veto_reason = scoring_report.veto.reason

        # ── 2. Determine market_state from klines ────────────────
        market_state = self._detect_market_state(klines, latest_indicators)

        # ── 3. News direction ────────────────────────────────────
        news_direction = self._extract_news_direction(news_report)

        # ── 4. Backtest win rate ─────────────────────────────────
        bt_win_rate = 0.0
        if backtest_result:
            bt_win_rate = backtest_result.get("win_rate", 0.0)

        # ── 5. Resolve direction ─────────────────────────────────
        direction = resolve_direction(
            final_score=fs,
            market_state=market_state,
            vetoed=vetoed,
            backtest_win_rate=bt_win_rate,
            news_direction=news_direction,
            scoring_decision=scoring_report.decision,
        )

        # ── 6. Conflict signals ──────────────────────────────────
        conflict_signals = self._detect_conflicts(
            scoring_report, news_report, market_state, klines
        )

        # ── 7. Build decision text fields ────────────────────────
        decision = ComprehensiveDecision(
            symbol=symbol,
            market_state=market_state,
            direction=direction,
            final_score=fs,
            confidence=scoring_report.confidence,
            entry_condition=self._build_entry_condition(
                direction, market_state, fs, scoring_report, klines
            ),
            invalid_condition=self._build_invalid_condition(
                direction, market_state, klines, latest_indicators
            ),
            stop_loss=self._build_stop_loss(
                direction, market_state, klines, latest_indicators
            ),
            take_profit=self._build_take_profit(
                direction, market_state, fs, latest_indicators
            ),
            position_suggestion=self._build_position_suggestion(
                direction, fs, scoring_report, backtest_result
            ),
            reason_summary=self._build_reason_summary(
                scoring_report, news_direction, market_state
            ),
            conflict_signals=conflict_signals,
            need_human_confirm=scoring_report.need_human_confirm,
            vetoed=vetoed,
            veto_reason=veto_reason,
        )

        # ── 8. Save ─────────────────────────────────────────────
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DECISION_PATH.write_text(decision.to_json())
        logger.info("Decision saved to %s", DECISION_PATH)

        self._print_decision(decision)
        return decision

    # ── Internal detectors ──────────────────────────────────────────

    @staticmethod
    def _detect_market_state(
        klines: list[dict[str, Any]] | None,
        indicators: dict[str, Any] | None,
    ) -> MarketState:
        """Detect market state from klines and indicators."""
        if not klines or len(klines) < 20:
            return "range"

        closes = [float(k["close"]) for k in klines[-20:]]
        highs = [float(k["high"]) for k in klines[-20:]]
        lows = [float(k["low"]) for k in klines[-20:]]

        # Trend strength
        slope = (closes[-1] - closes[0]) / closes[0] * 100
        # Volatility
        ranges = [(h - l) / l * 100 for h, l in zip(highs, lows)]
        avg_range = sum(ranges) / len(ranges)

        # Panic: 3 consecutive bearish candles with above-avg volume
        recent_closes = closes[-5:]
        bearish_streak = sum(
            1 for i in range(1, len(recent_closes))
            if recent_closes[i] < recent_closes[i - 1]
        )

        if slope < -5 and bearish_streak >= 3 and avg_range > 2.5:
            return "panic"
        if slope > 8 and avg_range > 2.5:
            # Check RSI for FOMO
            rsi = (indicators or {}).get("rsi", 50)
            if rsi and rsi > 68:
                return "fomo"
            return "trend"
        if abs(slope) > 3:
            return "trend"
        return "range"

    @staticmethod
    def _extract_news_direction(news_report: dict[str, Any] | None) -> str:
        """Extract aggregate news direction."""
        if not news_report or not news_report.get("reports"):
            return "neutral"
        directions = [r.get("direction", "neutral") for r in news_report["reports"]]
        bullish = sum(1 for d in directions if d == "bullish")
        bearish = sum(1 for d in directions if d == "bearish")
        if bullish > bearish and bullish >= 2:
            return "bullish"
        if bearish > bullish and bearish >= 2:
            return "bearish"
        return "neutral"

    @staticmethod
    def _detect_conflicts(
        scoring_report: Any,
        news_report: dict[str, Any] | None,
        market_state: MarketState,
        klines: list[dict[str, Any]] | None,
    ) -> list[str]:
        """Detect contradictory signals across dimensions."""
        conflicts: list[str] = []
        scores = scoring_report.scores

        # News bullish but kline bearish
        news_dir = ""
        if news_report and news_report.get("reports"):
            news_dir = (
                ComprehensiveDecisionAgent._extract_news_direction(news_report)
            )
        kline_sc = scores.kline_score
        if news_dir == "bullish" and kline_sc < 40:
            conflicts.append(
                f"新闻利好({news_dir})但K线评分低({kline_sc:.0f})，利好尚未被市场验证"
            )
        if news_dir == "bearish" and kline_sc > 70:
            conflicts.append(
                f"新闻利空({news_dir})但K线强势({kline_sc:.0f})，市场可能已消化利空"
            )

        # Tech bullish but fund flow weak
        tech_sc = scores.technical_score
        fund_sc = scores.fund_flow_score
        if tech_sc > 70 and fund_sc < 40:
            conflicts.append(
                f"技术面看多({tech_sc:.0f})但资金流入弱({fund_sc:.0f})，突破可能缺乏量能"
            )

        # Sentiment extreme but risk high
        sent_sc = scores.sentiment_score
        risk_dd = scores.risk_deduction
        if sent_sc > 80 and risk_dd > 20:
            conflicts.append(
                f"市场情绪过热(情感{sent_sc:.0f}分)，但风控扣除{risk_dd:.0f}分，警惕反向"
            )

        # Market state mismatch with backtest
        bt_sc = scores.backtest_score
        if market_state == "trend" and bt_sc < 40:
            conflicts.append("当前趋势行情，但回测策略在该环境下表现不佳")

        return conflicts

    # ── Text field builders ─────────────────────────────────────────

    @staticmethod
    def _build_entry_condition(
        direction: str,
        market_state: MarketState,
        fs: float,
        scoring_report: Any,
        klines: list[dict[str, Any]] | None,
    ) -> str:
        """Build entry condition — NOT "buy now"."""
        if direction == "wait" or fs < 60:
            return "未达交易阈值，等待信号确认"

        parts: list[str] = []

        # Price level suggestion
        if klines and len(klines) >= 5:
            recent_close = float(klines[-1]["close"])
            parts.append(f"价格确认在 {recent_close:.0f} 附近企稳")

        # Indicators condition
        s = scoring_report.scores
        if s.technical_score > 70:
            parts.append("技术指标共振（RSI+MACD+MA方向一致）")
        if s.event_score > 60:
            parts.append("新闻事件支持（利好确认）")
        if s.kline_score > 70:
            parts.append("K线形态突破确认后入场")

        if market_state == "trend":
            parts.insert(0, "回踩不破EMA21时入场")
        elif market_state == "range":
            parts.insert(0, "突破震荡区间上沿且放量时入场")

        return "；".join(parts) if parts else "等待明确入场信号"

    @staticmethod
    def _build_invalid_condition(
        direction: str,
        market_state: MarketState,
        klines: list[dict[str, Any]] | None,
        indicators: dict[str, Any] | None,
    ) -> str:
        """Build invalid condition — when to cancel the plan."""
        if direction == "wait":
            return "当前无有效计划"

        parts: list[str] = []

        if klines and len(klines) >= 5:
            recent_close = float(klines[-1]["close"])
            parts.append(f"价格跌破 {recent_close * 0.97:.0f}（-3%）")

        ema = (indicators or {}).get("ema_21")
        if ema:
            parts.append(f"EMA21({ema:.0f}) 破位")

        if market_state == "trend":
            parts.append("趋势结构破坏（更低的高点/更低的低点）")

        parts.append("新闻事件方向逆转")

        return " 或 ".join(parts) if parts else "监控失效条件"

    @staticmethod
    def _build_stop_loss(
        direction: str,
        market_state: MarketState,
        klines: list[dict[str, Any]] | None,
        indicators: dict[str, Any] | None,
    ) -> str:
        """Build stop loss condition."""
        if direction == "wait":
            return "N/A"

        parts: list[str] = []
        if klines and len(klines) >= 5:
            recent_close = float(klines[-1]["close"])
            parts.append(f"固定止损 {recent_close * 0.95:.0f}（-5%）")

        ema = (indicators or {}).get("ema_21")
        if ema:
            parts.append(f"EMA21 移动止损 ({ema:.0f})")

        atr = (indicators or {}).get("atr")
        if atr and klines:
            close = float(klines[-1]["close"])
            parts.append(f"1.5×ATR 止损 ({close - 1.5 * atr:.0f})")

        if market_state == "trend":
            return f"EMA21 移动止损（{ema:.0f}）或 -5% 固定止损"
        return " 或 ".join(parts) if parts else "未设置止损"

    @staticmethod
    def _build_take_profit(
        direction: str,
        market_state: MarketState,
        fs: float,
        indicators: dict[str, Any] | None,
    ) -> str:
        """Build take profit condition."""
        if direction == "wait":
            return "N/A"

        parts: list[str] = []

        parts.append(f"+{min(10 + fs * 0.05, 25):.0f}% 分批止盈")

        rsi = (indicators or {}).get("rsi")
        if rsi:
            parts.append(f"RSI > 70 减半仓")
            parts.append(f"RSI > 78 清仓")

        if market_state == "fomo":
            parts.insert(0, "FOMO行情止盈从宽，RSI 75 减半")

        return "；".join(parts)

    @staticmethod
    def _build_position_suggestion(
        direction: str,
        fs: float,
        scoring_report: Any,
        backtest_result: dict[str, Any] | None,
    ) -> str:
        """Build position suggestion — conservative by default."""
        if direction == "wait":
            return "0%（等待）"

        base_pct = 5  # default: 5%
        if fs >= 80:
            base_pct = 10
        elif fs >= 70:
            base_pct = 7

        # Backtest confidence boost
        if backtest_result:
            sample_ok = backtest_result.get("sample_sufficient", False)
            win_rate = backtest_result.get("win_rate", 0)
            if sample_ok and win_rate > 0.55:
                base_pct = min(base_pct + 3, 15)

        # Deduct for missing data
        for dim in scoring_report.dimensions:
            if dim.get("data_missing", False):
                base_pct = max(base_pct - 2, 3)

        return (
            f"{base_pct}% 初始仓位；确认趋势后加至 {min(base_pct * 2, 20)}%；"
            f"总仓位不超过 20%"
        )

    @staticmethod
    def _build_reason_summary(
        scoring_report: Any,
        news_direction: str,
        market_state: MarketState,
    ) -> list[str]:
        """Build 1-sentence reason bullets."""
        reasons: list[str] = []
        s = scoring_report.scores

        reasons.append(
            f"综合评分 {scoring_report.final_score:.1f}，"
            f"市场状态 {market_state.upper()}"
        )
        reasons.append(
            f"技术面 {s.technical_score:.0f}分 | "
            f"K线形态 {s.kline_score:.0f}分 | "
            f"新闻情感 {news_direction}"
        )
        reasons.append(
            f"事件评分 {s.event_score:.0f} | "
            f"资金流 {s.fund_flow_score:.0f} | "
            f"回测 {s.backtest_score:.0f}"
        )

        if s.risk_deduction > 10:
            reasons.append(f"风控扣除 {s.risk_deduction:.0f}分 — 注意风险")

        if scoring_report.veto.vetoed:
            reasons.append(f"⚠️ 已被否决: {scoring_report.veto.reason}")

        return reasons

    @staticmethod
    def _print_decision(d: ComprehensiveDecision) -> None:
        print("\n" + "=" * 60)
        print(f"  综合决策报告: {d.symbol} ({d.market_state})")
        print("=" * 60)
        print(f"  方向: {d.direction.upper()}    评分: {d.final_score:.1f}    信心: {d.confidence:.0%}")
        print(f"  入场条件: {d.entry_condition}")
        print(f"  失效条件: {d.invalid_condition}")
        print(f"  止损: {d.stop_loss}")
        print(f"  止盈: {d.take_profit}")
        print(f"  仓位: {d.position_suggestion}")
        if d.conflict_signals:
            print(f"\n  ⚠️ 矛盾信号:")
            for c in d.conflict_signals:
                print(f"    • {c}")
        if d.vetoed:
            print(f"\n  🛑 已被否决: {d.veto_reason}")
        print(f"\n  人工确认: {'需要' if d.need_human_confirm else '不需要'}")
        print(d.disclaimer())
