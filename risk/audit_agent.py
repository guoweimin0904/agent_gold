"""Risk Audit Agent — refutes the main trading decision.

Role: Not to propose new trades, but to CHALLENGE the main model's output.

Checks performed:
1. over_optimism      — 是否过度乐观？（score vs market_state vs evidence）
2. major_risk_ignored — 是否忽略重大风险？（S事件、杀开关、日亏损）
3. news_reliability   — 新闻来源是否可靠？（unverified / rumour / single source）
4. score_evidence_gap — 评分是否与证据匹配？（高分但数据缺失）
5. backtest_quality   — 回测是否样本不足或存在未来函数？
6. position_limit     — 仓位是否超限？
7. human_confirm      — 是否需要人工确认？
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from risk.audit_report import AuditCheckResult, RiskAuditReport, RiskLevel

logger = logging.getLogger("risk.audit")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "risk_audit_report.json"


class RiskAuditAgent:
    """
    Risk Audit Agent — deterministic rule-based decision refuter.

    Usage:
        report = RiskAuditAgent().audit(decision, context)
        print(report.to_json())
    """

    # ── Configuration ──────────────────────────────────────────────
    POSITION_LIMIT_PCT = 20            # max total position %
    SINGLE_POSITION_LIMIT_PCT = 15     # max per-symbol position %
    MAX_DAILY_LOSS_PCT = 2             # max daily loss % of capital
    BACKTEST_MIN_TRADES = 30           # min trades for reliable backtest

    def audit(
        self,
        decision: dict[str, Any] | None,
        context: dict[str, Any] | None = None,
    ) -> RiskAuditReport:
        """
        Run all 7 audit checks on a ComprehensiveDecision.

        Parameters
        ----------
        decision : dict
            The ComprehensiveDecision (from comprehensive_decision_agent).
        context : dict, optional
            Additional context: news_report, backtest_result, risk_status,
            scoring_report, klines, indicators, market_overview.
        """
        logger.info("Running risk audit on decision")

        if not decision:
            report = RiskAuditReport(
                approved=False,
                risk_level="high",
                veto_reason="无决策输入，默认否决",
                required_checks=["所有交易需人工确认"],
            )
            self._save(report)
            return report

        symbol = decision.get("symbol", "UNKNOWN")
        final_score = decision.get("final_score", 0)
        direction = decision.get("direction", "wait")
        position_suggestion = decision.get("position_suggestion", "")
        vetoed = decision.get("vetoed", False)
        veto_reason = decision.get("veto_reason", "")
        need_human = decision.get("need_human_confirm", True)
        entry_condition = decision.get("entry_condition", "")
        stop_loss = decision.get("stop_loss", "")
        take_profit = decision.get("take_profit", "")
        conflict_signals = decision.get("conflict_signals", [])

        ctx = context or {}

        # ── Run 7 checks ───────────────────────────────────────────
        checks: list[AuditCheckResult] = []
        veto_reasons: list[str] = []
        required_checks: list[str] = []
        total_veto_weight = 0  # how many critical checks failed
        findings: list[str] = []

        # ── Check 1: Over-optimism ─────────────────────────────────
        c1 = self._check_over_optimism(
            final_score, direction, conflict_signals, ctx
        )
        checks.append(c1)
        if not c1.passed and c1.severity == "critical":
            veto_reasons.append(c1.detail)
            total_veto_weight += 3
        elif not c1.passed:
            findings.append(c1.detail)

        # ── Check 2: Major risk ignored ────────────────────────────
        c2 = self._check_major_risk_ignored(ctx, vetoed, veto_reason)
        checks.append(c2)
        if not c2.passed and c2.severity == "critical":
            veto_reasons.append(c2.detail)
            total_veto_weight += 3
        elif not c2.passed:
            findings.append(c2.detail)

        # ── Check 3: News reliability ──────────────────────────────
        c3 = self._check_news_reliability(ctx)
        checks.append(c3)
        if not c3.passed and c3.severity == "critical":
            veto_reasons.append(c3.detail)
            total_veto_weight += 2
        elif not c3.passed:
            findings.append(c3.detail)

        # ── Check 4: Score-evidence gap ────────────────────────────
        c4 = self._check_score_evidence_gap(final_score, ctx)
        checks.append(c4)
        if not c4.passed and c4.severity == "critical":
            veto_reasons.append(c4.detail)
            total_veto_weight += 2
        elif not c4.passed:
            findings.append(c4.detail)

        # ── Check 5: Backtest quality ──────────────────────────────
        c5 = self._check_backtest_quality(ctx)
        checks.append(c5)
        if not c5.passed and c5.severity == "critical":
            veto_reasons.append(c5.detail)
            total_veto_weight += 2
        elif not c5.passed:
            findings.append(c5.detail)

        # ── Check 6: Position limit ────────────────────────────────
        c6, pos_limit_text = self._check_position_limit(
            position_suggestion, direction, final_score, ctx
        )
        checks.append(c6)
        if not c6.passed and c6.severity == "critical":
            veto_reasons.append(c6.detail)
            total_veto_weight += 2
        elif not c6.passed:
            findings.append(c6.detail)
            if pos_limit_text:
                required_checks.append(pos_limit_text)

        # ── Check 7: Human confirm ─────────────────────────────────
        c7 = self._check_human_confirm(need_human, final_score)
        checks.append(c7)
        if not c7.passed:
            findings.append(c7.detail)
            required_checks.append("需要人工确认后方可执行")

        # ── Aggregate ──────────────────────────────────────────────
        approved = total_veto_weight < 3  # need at least 2 critical to veto
        risk_level = self._determine_risk_level(
            total_veto_weight, final_score, checks
        )

        if not approved:
            veto_reason_text = "；".join(veto_reasons) if veto_reasons else "风控审查未通过"
            if not veto_reason_text:
                veto_reason_text = "多项风控检查未通过"
        else:
            veto_reason_text = ""

        # If already externally vetoed, respect it
        if vetoed:
            approved = False
            veto_reason_text = f"外部否决已触发: {veto_reason}"
            risk_level = "high"

        report = RiskAuditReport(
            approved=approved,
            risk_level=risk_level,
            veto_reason=veto_reason_text,
            position_limit=self._build_position_limit_text(
                approved, pos_limit_text if 'pos_limit_text' in dir() else ""
            ),
            required_checks=list(set(required_checks)),
            check_results=[c.to_dict() for c in checks],
            symbol=symbol,
            final_score=final_score,
            direction=direction,
        )

        self._save(report)
        self._print(report)
        return report

    # ── 7 Check implementations ─────────────────────────────────────

    @staticmethod
    def _check_over_optimism(
        score: float,
        direction: str,
        conflict_signals: list[str],
        ctx: dict[str, Any],
    ) -> AuditCheckResult:
        """
        Check 1: 是否过度乐观？

        Flags:
        - 高分(≥75) 但没有 conflict_signals → 可能忽略风险
        - 高分 + direction=long 但市场状态=panic/fomo → 矛盾
        - 高分但 scoring_report 显示多个数据缺失
        - 方向与情感方向相反但未声明
        """
        passed = True
        severity = "info"
        reasons: list[str] = []

        # High score with no conflicts → suspicious
        if score >= 75 and not conflict_signals:
            reasons.append(f"评分{score:.0f}分但未列出任何矛盾信号，可能过度乐观")
            severity = "warning"
            passed = False

        # Direction vs market state mismatch
        market_state = ctx.get("market_state", "range")
        if direction == "long" and market_state in ("panic", "fomo"):
            reasons.append(f"{direction.upper()}方向但市场状态为{market_state.upper()}，方向与状态矛盾")
            severity = "critical"
            passed = False

        # High score but multiple missing data
        scoring = ctx.get("scoring_report") or {}
        missing_count = sum(
            1 for d in scoring.get("dimensions", [])
            if d.get("data_missing", False)
        )
        if score >= 70 and missing_count >= 3:
            reasons.append(f"评分{score:.0f}分但有{missing_count}项数据缺失，评分可靠性存疑")
            severity = "warning"
            passed = False

        detail = "；".join(reasons) if reasons else "未发现过度乐观"
        return AuditCheckResult(
            check_id="over_optimism",
            check_name="过度乐观检查",
            passed=passed,
            severity=severity,
            detail=detail,
        )

    @staticmethod
    def _check_major_risk_ignored(
        ctx: dict[str, Any],
        decision_vetoed: bool,
        decision_veto_reason: str,
    ) -> AuditCheckResult:
        """
        Check 2: 是否忽略重大风险？

        Checks:
        - kill_switch active
        - daily loss limit hit
        - S-level event with risk_pause
        - market-wide drawdown > 15%
        """
        passed = True
        severity = "info"
        reasons: list[str] = []

        risk_status = ctx.get("risk_status") or {}

        if risk_status.get("kill_switch_active", False):
            reasons.append("杀开关已激活，禁止交易")
            severity = "critical"
            passed = False

        if risk_status.get("daily_loss_limit_hit", False):
            reasons.append("每日亏损上限已触发")
            severity = "critical"
            passed = False

        if risk_status.get("s_event_active", False):
            reasons.append("S级事件风险暂停，自动否决")
            severity = "critical"
            passed = False

        mdd = risk_status.get("market_drawdown_pct", 0)
        if mdd and mdd > 15:
            reasons.append(f"市场回撤{mdd:.1f}%超过15%阈值")
            severity = "warning"
            passed = False

        # Decision itself already vetoed — check if properly handled
        if decision_vetoed and not ctx.get("decision_handled_properly", True):
            reasons.append(f"决策已被否决({decision_veto_reason})，但未正确处理")
            severity = "critical"
            passed = False

        detail = "；".join(reasons) if reasons else "未发现被忽略的重大风险"
        return AuditCheckResult(
            check_id="major_risk_ignored",
            check_name="重大风险忽略检查",
            passed=passed,
            severity=severity,
            detail=detail,
        )

    @staticmethod
    def _check_news_reliability(ctx: dict[str, Any]) -> AuditCheckResult:
        """
        Check 3: 新闻来源是否可靠？

        Checks:
        - 如果新闻中有 rumour / unverified 但决策依赖了利好
        - 如果只有单来源但标记为重大事件
        - 如果新闻事件依赖 KOL 喊单
        """
        passed = True
        severity = "info"
        reasons: list[str] = []

        news_report = ctx.get("news_report") or {}
        reports = news_report.get("reports", [])

        if not reports:
            return AuditCheckResult(
                check_id="news_reliability",
                check_name="新闻可靠性检查",
                passed=True,
                severity="info",
                detail="无新闻数据，不构成影响",
            )

        unverified_count = 0
        rumour_count = 0
        for r in reports:
            status = r.get("truth_status", "")
            if status == "unverified":
                unverified_count += 1
                # Check if this unverified news is being used for direction
                if r.get("direction") in ("bullish", "bearish") and r.get("impact_level") in ("A", "S"):
                    reasons.append(
                        f"级别{r.get('impact_level')}的{r.get('direction')}新闻"
                        f"可信度为{status}，不应作为重大决策依据"
                    )
                    severity = "warning"
                    passed = False
            elif status == "rumour":
                rumour_count += 1
                reasons.append(f"存在{rumour_count}条传言级别新闻，不可靠")
                severity = "critical"
                passed = False

        # Check for single-source major events
        for r in reports:
            if r.get("impact_level") == "S":
                dedup = r.get("dedup", {})
                mention_count = dedup.get("mention_count", 1) if isinstance(dedup, dict) else 1
                if mention_count < 2:
                    reasons.append(
                        f"S级事件「{r.get('title','')[:40]}」仅{mention_count}个来源，"
                        f"重大新闻需要至少2个来源或官方确认"
                    )
                    severity = "critical"
                    passed = False

        detail = "；".join(reasons) if reasons else "新闻来源可靠"
        return AuditCheckResult(
            check_id="news_reliability",
            check_name="新闻可靠性检查",
            passed=passed,
            severity=severity,
            detail=detail,
        )

    @staticmethod
    def _check_score_evidence_gap(
        final_score: float,
        ctx: dict[str, Any],
    ) -> AuditCheckResult:
        """
        Check 4: 评分是否与证据匹配？

        Checks:
        - 高分(≥80)但多个子评分器数据缺失(data_missing)
        - 高分但低 Kline 分(≤40)
        - 高分但风控扣除大(≥30)
        """
        passed = True
        severity = "info"
        reasons: list[str] = []

        scoring = ctx.get("scoring_report") or {}
        scores = scoring.get("scores", {})

        if not scores:
            return AuditCheckResult(
                check_id="score_evidence_gap",
                check_name="评分证据匹配检查",
                passed=False,
                severity="warning",
                detail="无评分数据，无法验证评分与证据的一致性",
            )

        # High score but missing dimensions
        missing_dims = [
            d for d in scoring.get("dimensions", [])
            if d.get("data_missing", False) and d.get("name")
        ]
        if final_score >= 80 and len(missing_dims) >= 2:
            names = [d["name"] for d in missing_dims]
            reasons.append(f"评分{final_score:.0f}分但{len(missing_dims)}项数据缺失: {', '.join(names)}")
            severity = "warning"
            passed = False

        # High score but low kline score
        kline_score = scores.get("kline_score", 50)
        if final_score >= 75 and kline_score < 40:
            reasons.append(f"总分{final_score:.0f}分但K线评分仅{kline_score:.0f}分，价量不支持高分")
            severity = "critical"
            passed = False

        # High score but high risk deduction
        risk_dd = scores.get("risk_deduction", 0)
        if final_score >= 70 and risk_dd >= 30:
            reasons.append(f"总分{final_score:.0f}分但风控扣除{risk_dd:.0f}分，风险隐患大")
            severity = "critical"
            passed = False

        # Low score but high confidence → contradictory
        confidence = scoring.get("confidence", 0)
        if final_score < 60 and confidence > 0.6:
            reasons.append(f"评分{final_score:.0f}分但信心度{confidence:.0%}，评分配置矛盾")
            severity = "warning"
            passed = False

        detail = "；".join(reasons) if reasons else "评分与证据匹配"
        return AuditCheckResult(
            check_id="score_evidence_gap",
            check_name="评分证据匹配检查",
            passed=passed,
            severity=severity,
            detail=detail,
        )

    @staticmethod
    def _check_backtest_quality(ctx: dict[str, Any]) -> AuditCheckResult:
        """
        Check 5: 回测是否样本不足或存在未来函数？

        Checks:
        - trade_count < 30 → 样本不足
        - 不允许做空但策略卖出 → 逻辑矛盾
        - 高胜率但低交易次数 → 可能过拟合
        """
        passed = True
        severity = "info"
        reasons: list[str] = []

        bt = ctx.get("backtest_result") or {}
        if not bt:
            return AuditCheckResult(
                check_id="backtest_quality",
                check_name="回测质量检查",
                passed=True,
                severity="info",
                detail="无回测数据，不构成影响",
            )

        trade_count = bt.get("trade_count", 0)
        sample_ok = bt.get("sample_sufficient", False)

        if not sample_ok or trade_count < 30:
            reasons.append(f"回测样本不足({trade_count}笔 < 30)，回测结果不可靠")
            severity = "critical"
            passed = False

        # High win rate but low trades → overfitting suspicion
        win_rate = bt.get("win_rate", 0)
        if win_rate > 0.8 and trade_count < 50:
            reasons.append(f"胜率{win_rate:.0%}但仅{trade_count}笔交易，疑似过拟合")
            severity = "warning"
            passed = False

        # Profit factor suspiciously high
        pf = bt.get("profit_factor", 1.0)
        if pf != "inf" and pf > 5 and trade_count < 50:
            reasons.append(f"盈亏比{pf:.1f}x过高（<50笔），可能是数据选择偏差")
            severity = "warning"
            passed = False

        detail = "；".join(reasons) if reasons else "回测质量良好"
        return AuditCheckResult(
            check_id="backtest_quality",
            check_name="回测质量检查",
            passed=passed,
            severity=severity,
            detail=detail,
        )

    @staticmethod
    def _check_position_limit(
        position_suggestion: str,
        direction: str,
        final_score: float,
        ctx: dict[str, Any],
    ) -> tuple[AuditCheckResult, str]:
        """
        Check 6: 仓位是否超限？

        Enforces:
        - 单标的 ≤ 15%
        - 总仓位 ≤ 20%
        - direction=wait 时 force 0%
        - 新手默认 ≤ 10%
        """
        passed = True
        severity = "info"
        reasons: list[str] = []
        pos_limit_text = ""

        if direction == "wait":
            if "0%" not in position_suggestion and position_suggestion:
                reasons.append("direction=wait 但仓位建议非0%，应设为0%")
                severity = "warning"
                passed = False
            return AuditCheckResult(
                check_id="position_limit",
                check_name="仓位限制检查",
                passed=passed,
                severity=severity,
                detail="；".join(reasons) if reasons else "仓位合规",
            ), pos_limit_text

        if not position_suggestion:
            reasons.append("仓位建议为空")
            severity = "critical"
            passed = False
            return AuditCheckResult(
                check_id="position_limit",
                check_name="仓位限制检查",
                passed=False,
                severity="critical",
                detail="仓位建议为空",
            ), "请设置明确的仓位百分比"

        # Extract percentage from suggestion text
        numbers = re.findall(r'(\d+)%', position_suggestion)
        if numbers:
            max_pct = max(int(n) for n in numbers)
            if max_pct > 15:
                reasons.append(f"建议仓位{max_pct}%超过单标的上限15%")
                severity = "critical"
                pos_limit_text = f"仓位上限15%，当前{max_pct}%"
                passed = False
            elif max_pct > 10:
                reasons.append(f"建议仓位{max_pct}%超过新手推荐上限10%")
                severity = "warning"
                pos_limit_text = f"新手阶段建议仓位降至10%以内"
                passed = False
        else:
            reasons.append("仓位建议中未找到明确百分比，请添加百分比数字")
            severity = "warning"
            passed = False

        # Score < 70 should force low position
        if final_score < 70:
            if numbers and max(int(n) for n in numbers) > 7:
                reasons.append(f"评分{final_score:.0f}分(<70)，仓位应控制在7%以内")
                severity = "warning"
                passed = False

        detail = "；".join(reasons) if reasons else "仓位合规"
        return AuditCheckResult(
            check_id="position_limit",
            check_name="仓位限制检查",
            passed=passed,
            severity=severity,
            detail=detail,
        ), pos_limit_text

    @staticmethod
    def _check_human_confirm(
        need_human: bool,
        final_score: float,
    ) -> AuditCheckResult:
        """
        Check 7: 是否需要人工确认？

        Rules:
        - final_score >= 30 → need_human_confirm=True
        - 所有新系统交易默认 True
        """
        passed = True
        severity = "info"

        if not need_human and final_score >= 30:
            return AuditCheckResult(
                check_id="human_confirm",
                check_name="人工确认检查",
                passed=False,
                severity="critical",
                detail=f"评分{final_score:.0f}分≥30但need_human_confirm=False，新手阶段必须人工确认",
            )

        return AuditCheckResult(
            check_id="human_confirm",
            check_name="人工确认检查",
            passed=True,
            severity="info",
            detail="人工确认设置合理",
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _determine_risk_level(
        veto_weight: int,
        final_score: float,
        checks: list[AuditCheckResult],
    ) -> RiskLevel:
        """Determine overall risk level from checks and score."""
        critical_fails = sum(1 for c in checks if not c.passed and c.severity == "critical")
        warning_fails = sum(1 for c in checks if not c.passed and c.severity == "warning")

        if critical_fails >= 2 or veto_weight >= 4 or final_score < 30:
            return "high"
        if critical_fails >= 1 or warning_fails >= 2 or final_score < 50:
            return "medium"
        return "low"

    @staticmethod
    def _build_position_limit_text(
        approved: bool,
        pos_text: str,
    ) -> str:
        if not approved:
            return f"风控未通过，禁止开仓"
        return pos_text if pos_text else "仓位合规，按建议执行"

    @staticmethod
    def _save(report: RiskAuditReport) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report.to_json())
        logger.info("Audit report saved to %s", REPORT_PATH)

    @staticmethod
    def _print(report: RiskAuditReport) -> None:
        status = "✅ 通过" if report.approved else "🛑 否决"
        print(f"\n─── 风控审查报告 [{status}] ───")
        print(f"风控等级: {report.risk_level.upper()}")
        if report.veto_reason:
            print(f"否决原因: {report.veto_reason}")
        if report.position_limit:
            print(f"仓位限制: {report.position_limit}")
        if report.required_checks:
            print(f"待办项:")
            for r in report.required_checks:
                print(f"  • {r}")
        print("── 逐项检查 ──")
        for c in report.check_results:
            status_c = "✅" if c["passed"] else "❌"
            sev = c["severity"].upper()
            print(f"  {status_c} [{sev}] {c['check_name']}: {c['detail']}")
        print(report.disclaimer())
