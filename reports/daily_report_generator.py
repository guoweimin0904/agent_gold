"""Daily Report Generator — produces a structured Markdown daily trading report.

Combines data from:
- market_snapshot.json (klines, market_overview)
- news_report.json (news classification)
- scoring_report.json (7-dimension scores)
- comprehensive_decision.json (decision output)
- risk_audit_report.json (audit results)
- backtest results (from data/backtest/)
- execution_gate_output.json (gate results)
- opportunity_batch.json (scanner results)

7 Sections:
1. 今日市场状态
2. 重要事件摘要
3. 策略回测结果
4. 今日评分卡
5. 模拟交易建议
6. 风控复核结论
7. 复盘备注
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("reports.daily")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_DIR = Path(__file__).resolve().parent / "generated"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class DailyReportGenerator:
    """
    Generate a structured Markdown daily trading report.

    Usage:
        report = DailyReportGenerator().generate(symbol="BTCUSDT")
        print(report)
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def generate(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        date_str: str | None = None,
    ) -> str:
        """Generate the full Markdown report."""
        date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # ── Load all available data ────────────────────────────────
        self._load_all_data(symbol)

        # ── Assemble sections ──────────────────────────────────────
        sections = [
            self._header(symbol, timeframe, date_str),
            self._section_market_state(symbol, date_str),
            self._section_events(),
            self._section_backtest(symbol),
            self._section_scoring(),
            self._section_trade_decision(symbol),
            self._section_risk_audit(),
            self._section_review(),
            self._footer(),
        ]
        report = "\n\n".join(sections)

        # ── Save ───────────────────────────────────────────────────
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"daily_report_{date_str}.md"
        path.write_text(report)
        logger.info("Report saved: %s", path)

        return report

    # ── Data loading ───────────────────────────────────────────────

    def _load_all_data(self, symbol: str) -> None:
        """Load all available data files into self._data."""
        files = {
            "market_snapshot": DATA_DIR / "market_snapshot.json",
            "news_report": DATA_DIR / "news_report.json",
            "scoring_report": DATA_DIR / "scoring_report.json",
            "decision": DATA_DIR / "comprehensive_decision.json",
            "risk_audit": DATA_DIR / "risk_audit_report.json",
            "execution_gate": DATA_DIR / "execution_gate_output.json",
            "opportunity": DATA_DIR / "opportunity_batch.json",
            "backtest_btc": DATA_DIR / "backtest" / f"{symbol}_1h_backtest.json",
            "backtest_eth": DATA_DIR / "backtest" / "ETHUSDT_1h_backtest.json",
        }
        for key, path in files.items():
            if path.exists():
                try:
                    self._data[key] = json.loads(path.read_text())
                except Exception as e:
                    logger.warning("Failed to load %s: %s", key, e)
                    self._data[key] = {}
            else:
                self._data[key] = {}

    # ── Section builders ───────────────────────────────────────────

    @staticmethod
    def _header(symbol: str, timeframe: str, date: str) -> str:
        return (
            f"# 🤖 AI 量化交易日报 — {date}\n\n"
            f"> 生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"> 监控标的: {symbol} | 周期: {timeframe}\n"
            f"> ⚠️ 本报告仅供研究参考，不构成任何投资建议。"
        )

    def _section_market_state(self, symbol: str, date: str) -> str:
        """Section 1: 今日市场状态"""
        snap = self._data.get("market_snapshot", {})
        opp = self._data.get("opportunity", {})
        lines = ["## 📊 1. 今日市场状态\n"]

        # BTC/ETH price
        overview = snap.get("market_overview", [])
        btc_info = next((o for o in overview if o.get("symbol") == "BTCUSDT"), None)
        eth_info = next((o for o in overview if o.get("symbol") == "ETHUSDT"), None)

        lines.append("### 主要标的价格")
        if btc_info:
            p = btc_info.get("price", "N/A")
            chg = btc_info.get("price_change_24h_pct", 0)
            vol = btc_info.get("volume_24h", 0)
            lines.append(
                f"- **BTC**: ${p:,.2f}" if isinstance(p, (int, float)) else f"- **BTC**: {p}"
            )
            if isinstance(chg, (int, float)):
                lines.append(f"  - 24h涨跌: {chg:+.2f}%")
            if isinstance(vol, (int, float)):
                lines.append(f"  - 24h成交量: ${vol:,.0f}")
        else:
            lines.append("- BTC: 无数据")

        if eth_info:
            p = eth_info.get("price", "N/A")
            chg = eth_info.get("price_change_24h_pct", 0)
            lines.append(
                f"- **ETH**: ${p:,.2f}" if isinstance(p, (int, float)) else f"- **ETH**: {p}"
            )
            if isinstance(chg, (int, float)):
                lines.append(f"  - 24h涨跌: {chg:+.2f}%")
        else:
            lines.append("- ETH: 无数据")

        # Volatility / sentiment from opportunity scanner
        lines.append("\n### 波动率与情绪")
        breakout_sig = next(
            (s for s in opp.get("signals", []) if s.get("signal_type") == "breakout"),
            None,
        )
        if breakout_sig and breakout_sig.get("kline_score", 0) > 0:
            lines.append(f"- K线形态评分: {breakout_sig['kline_score']:.0f}/100")
            lines.append(f"- 突破信号: {'✅' if breakout_sig.get('breakout') else '❌'}")
            lines.append(f"- 放量确认: {'✅' if breakout_sig.get('volume_confirmed') else '❌'}")

        sent_sig = next(
            (s for s in opp.get("signals", []) if s.get("signal_type") == "extreme_sentiment"),
            None,
        )
        if sent_sig:
            lines.append(f"- 情绪评分: {sent_sig.get('sentiment_score', 50):.0f}/100")
            lines.append(f"- 极端情绪: {'⚠️ 是' if sent_sig.get('is_extreme') else '✅ 否'}")
            if sent_sig.get("contrarian_signal"):
                lines.append(f"- 反向信号: 💡 存在反向交易机会")

        # Market state from decision
        decision = self._data.get("decision", {})
        ms = decision.get("market_state", "N/A")
        lines.append(f"- 市场状态: **{ms.upper()}**")

        if not sent_sig and not breakout_sig:
            lines.append("- 暂无详细情绪/波动率数据")

        return "\n".join(lines)

    def _section_events(self) -> str:
        """Section 2: 重要事件摘要"""
        news = self._data.get("news_report", {})
        reports = news.get("reports", [])
        opp = self._data.get("opportunity", {})

        lines = ["## 📰 2. 重要事件摘要\n"]

        # From news pipeline
        if reports:
            for i, r in enumerate(reports[:5], 1):
                title = r.get("title", "(无标题)")[:60]
                source = r.get("source", "未知")
                level = r.get("impact_level", "C")
                direction = r.get("direction", "neutral")
                truth = r.get("truth_status", "unverified")
                cred = r.get("credibility", 0)
                risk_pause = "🛑" if r.get("risk_pause") else ""
                symbols = r.get("related_symbols", [])
                sym_str = ", ".join(symbols) if symbols else "N/A"

                lines.append(f"**事件{i}**: {risk_pause} {title}")
                lines.append(f"  - 来源: {source} | 可信度: {truth}({cred:.0%})")
                lines.append(f"  - 影响等级: {level} | 方向: {direction}")
                lines.append(f"  - 相关标的: {sym_str}")
                lines.append("")
        else:
            lines.append("- 当前无有效新闻数据或新闻缺失")

        # From listing scanner
        listing_sig = next(
            (s for s in opp.get("signals", []) if s.get("signal_type") == "listing"),
            None,
        )
        if listing_sig and listing_sig.get("event_score", 0) > 0:
            lines.append(f"**上币事件**: event_score={listing_sig['event_score']:.0f}")
            lines.append(f"  - 提前拉升: {listing_sig.get('already_pumped', 0):.0%}")
            lines.append(f"  - 交易窗口: {listing_sig.get('trade_window', '未知')}")
            lines.append("")

        return "\n".join(lines)

    def _section_backtest(self, symbol: str) -> str:
        """Section 3: 策略回测结果"""
        # Try symbol-specific backtest, fallback to any
        bt = self._data.get("backtest_btc", {})
        if not bt:
            bt = self._data.get("backtest_eth", {})

        lines = ["## 📈 3. 策略回测结果\n"]

        if not bt:
            lines.append("> 暂无回测数据。请运行 `python3 -m backtest.runner` 生成。")
            return "\n".join(lines)

        strategy = bt.get("symbol", symbol)
        interval = bt.get("interval", "1h")
        trade_count = bt.get("trade_count", 0)
        total_return = bt.get("total_return_pct", 0)
        max_dd = bt.get("max_drawdown_pct", 0)
        win_rate = bt.get("win_rate", 0)
        profit_factor = bt.get("profit_factor", 1.0)
        sample_ok = bt.get("sample_sufficient", False)
        trades = bt.get("trades", [])

        lines.append(f"- **策略**: MA5/20 金叉死叉")
        lines.append(f"- **标的**: {strategy} ({interval})")
        lines.append(f"- **交易次数**: {trade_count}")
        lines.append(f"- **总收益率**: {total_return:+.2f}%")
        lines.append(f"- **最大回撤**: {max_dd:.2f}%")
        lines.append(f"- **胜率**: {win_rate:.2%}")
        lines.append(f"- **盈亏比**: {profit_factor if isinstance(profit_factor, str) else f'{profit_factor:.2f}'}")
        lines.append(
            f"- **样本充足**: {'✅ 是' if sample_ok else '⚠️ 否 — 结论仅供参考'}"
        )

        if not sample_ok:
            lines.append(
                "\n> ⚠️ 样本不足（交易次数 < 30），回测结论不可靠，请勿仅据此决策。"
            )

        # Last 5 trades
        if trades:
            lines.append(f"\n### 最近交易明细")
            for t in trades[-5:]:
                entry_t = t.get("entry_time", "?")[-19:-6] if t.get("entry_time") else "?"
                exit_t = t.get("exit_time", "?")[-19:-6] if t.get("exit_time") else "?"
                pnl = t.get("pnl", 0)
                reason = t.get("reason", "")[:40]
                lines.append(
                    f"- {entry_t} → {exit_t} | PnL: {pnl:+.2f} | {reason}"
                )

        return "\n".join(lines)

    def _section_scoring(self) -> str:
        """Section 4: 今日评分卡"""
        scoring = self._data.get("scoring_report", {})
        scores = scoring.get("scores", {})

        lines = ["## 🎯 4. 今日评分卡\n"]

        if not scores:
            lines.append("> 暂无评分数据。请先运行评分引擎。")
            return "\n".join(lines)

        # Define score items with labels
        score_items = [
            ("事件评分", "event_score", "📰"),
            ("情感评分", "sentiment_score", "💬"),
            ("K线评分", "kline_score", "📊"),
            ("技术评分", "technical_score", "🔧"),
            ("资金评分", "fund_flow_score", "💰"),
            ("回测评分", "backtest_score", "📈"),
            ("风险扣分", "risk_deduction", "⚠️"),
        ]

        # Build score bar
        for label, key, icon in score_items:
            val = scores.get(key, 0)
            bar_len = int(val / 5)  # 0-20 bar chars
            bar = "█" * bar_len + "░" * (20 - bar_len)
            val_str = f"{val:.0f}" if key != "risk_deduction" else f"-{val:.0f}"
            lines.append(f"{icon} **{label}**: {val_str:>5s}  `{bar}`")

        # Final score
        final_score = scoring.get("final_score", 0)
        decision = scoring.get("decision", "avoid")
        confidence = scoring.get("confidence", 0)
        lines.append("")
        lines.append(f"### 综合评分: **{final_score:.1f}** / 100")
        lines.append(f"决策: **{decision}** | 信心度: {confidence:.0%}")
        if final_score >= 80:
            lines.append("> ✅ 强候选 — 多个维度信号一致")
        elif final_score >= 70:
            lines.append("> 🟡 候选 — 需要进一步确认")
        elif final_score >= 60:
            lines.append("> ⚠️ 观察 — 风险收益比一般")
        else:
            lines.append("> 🛑 避免交易 — 评分不足")

        return "\n".join(lines)

    def _section_trade_decision(self, symbol: str) -> str:
        """Section 5: 模拟交易建议"""
        decision = self._data.get("decision", {})

        lines = ["## 💡 5. 模拟交易建议\n"]

        if not decision:
            lines.append("> 暂无决策数据。请先运行决策引擎。")
            return "\n".join(lines)

        direction = decision.get("direction", "wait")
        final_score = decision.get("final_score", 0)
        confidence = decision.get("confidence", 0)
        vetoed = decision.get("vetoed", False)
        need_human = decision.get("need_human_confirm", True)

        # Direction emoji
        dir_emoji = {"long": "📈 LONG", "short": "📉 SHORT", "wait": "⏳ WAIT"}.get(
            direction, "⏳"
        )
        lines.append(f"**方向**: {dir_emoji}")

        lines.append(f"**入场条件**: {decision.get('entry_condition', 'N/A')}")
        lines.append(f"**止损**: {decision.get('stop_loss', 'N/A')}")
        lines.append(f"**止盈**: {decision.get('take_profit', 'N/A')}")
        lines.append(f"**失效条件**: {decision.get('invalid_condition', 'N/A')}")
        lines.append(f"**仓位建议**: {decision.get('position_suggestion', '0%')}")

        # Human confirm
        if need_human:
            lines.append("\n> 👤 **需要人工确认** — 新手阶段所有交易均需人工批准")
        else:
            lines.append("\n> 🤖 自动决策 — 评分<30自动拒绝，无需人工")

        # Veto
        if vetoed:
            lines.append(
                f"\n> 🛑 **已被否决**: {decision.get('veto_reason', '风控否决')}"
            )

        # Conflict signals
        conflicts = decision.get("conflict_signals", [])
        if conflicts:
            lines.append("\n**⚠️ 矛盾信号**:")
            for c in conflicts:
                lines.append(f"- {c}")

        # Reasoning
        reasons = decision.get("reason_summary", [])
        if reasons:
            lines.append("\n**决策理由**:")
            for r in reasons:
                lines.append(f"- {r}")

        lines.append(f"\n**信心指数**: {confidence:.0%}")
        lines.append(f"**综合评分**: {final_score:.1f}")

        return "\n".join(lines)

    def _section_risk_audit(self) -> str:
        """Section 6: 风控复核结论"""
        audit = self._data.get("risk_audit", {})
        exec_gate = self._data.get("execution_gate", {})

        lines = ["## 🔒 6. 风控复核结论\n"]

        # Execute gate result
        gate_approved = exec_gate.get("approved", False)
        if exec_gate:
            if gate_approved:
                lines.append(f"> ✅ **执行门: 通过** — 所有7项安全检查通过")
                lines.append(f"> 模式: {exec_gate.get('execution_mode', 'paper')}")
                lines.append(f"> 仓位: {exec_gate.get('position_pct', 0):.1f}% "
                             f"({exec_gate.get('quantity_usdt', 0):.0f} USDT)")
            else:
                reject = exec_gate.get("reject_reason", "不执行")
                lines.append(f"> 🛑 **执行门: 不执行** — {reject[:60]}")

        lines.append("")

        # Risk audit result
        audit_approved = audit.get("approved", True)
        risk_level = audit.get("risk_level", "low")
        veto_reason = audit.get("veto_reason", "")
        position_limit = audit.get("position_limit", "")
        checks = audit.get("check_results", [])

        status = (
            "✅ 通过" if audit_approved and gate_approved else
            "🛑 不通过" if not audit_approved else "⚠️ 需要更多数据"
        )
        lines.append(f"**风控审查结论: {status}**")
        lines.append(f"**风控等级**: {risk_level.upper()}")

        if veto_reason:
            lines.append(f"**否决原因**: {veto_reason}")

        if position_limit:
            lines.append(f"**仓位限制**: {position_limit}")

        # Detail per check
        if checks:
            lines.append("\n**逐项审查结果**:")
            for c in checks:
                cid = c.get("check_id", "unknown")
                cname = c.get("check_name", cid)
                passed = c.get("passed", True)
                detail = c.get("detail", "")[:50]
                icon = "✅" if passed else "❌"
                lines.append(f"- {icon} {cname}: {detail}")

        # Required checks
        required = audit.get("required_checks", [])
        if required:
            lines.append("\n**待办事项**:")
            for r in required:
                lines.append(f"- 📋 {r}")

        return "\n".join(lines)

    def _section_review(self) -> str:
        """Section 7: 复盘备注"""
        decision = self._data.get("decision", {})
        exec_gate = self._data.get("execution_gate", {})
        opp = self._data.get("opportunity", {})

        lines = ["## 📝 7. 复盘备注\n"]

        # Was signal executed?
        gate_approved = exec_gate.get("approved", False)
        direction = decision.get("direction", "wait")
        vetoed = decision.get("vetoed", False)

        if gate_approved and direction != "wait":
            lines.append("**本次信号**: ✅ **已执行**")
            lines.append(
                f"  - 方向: {direction.upper()}"
            )
            lines.append(
                f"  - 仓位: {exec_gate.get('position_pct', 0):.1f}% "
                f"({exec_gate.get('quantity_usdt', 0):.0f} USDT)"
            )
            lines.append("  - 执行后结果: ⏳ 待下次日报更新")
        elif vetoed:
            lines.append("**本次信号**: 🛑 **未执行 (被否决)**")
            lines.append(f"  - 原因: {decision.get('veto_reason', '风控否决')}")
        elif direction == "wait":
            lines.append("**本次信号**: ⏳ **未执行 (等待)**")
            lines.append("  - 当前无符合条件的机会")
        else:
            lines.append("**本次信号**: ❌ **未执行**")
            reject = exec_gate.get("reject_reason", "执行门未通过")
            lines.append(f"  - 原因: {reject[:60]}")

        # Best candidate from opportunity scanner
        best = opp.get("best_candidate")
        if best:
            lines.append(f"\n**机会扫描最佳候选**:")
            lines.append(f"  - Type: {best.get('type', 'N/A')} | "
                         f"Score: {best.get('score', 0)} | "
                         f"Priority: {best.get('priority', 'none')}")

        # Next optimization suggestions
        lines.append("\n**下次需优化的规则**:")
        suggestions = []

        # Check if backtest sample insufficient
        bt_btc = self._data.get("backtest_btc", {})
        if bt_btc and not bt_btc.get("sample_sufficient", False):
            suggestions.append("- 回测样本不足，需收集更多历史数据进行验证")
        if exec_gate and not exec_gate.get("approved"):
            suggestions.append("- 执行门未通过，需检查具体拒绝项并修复")
        if decision and not decision.get("stop_loss"):
            suggestions.append("- 交易决策缺少止损条件，需在决策引擎中补全")

        # General suggestions
        suggestions.append("- 持续监控策略表现，评估是否需要调整MA周期参数")
        suggestions.append("- 关注市场状态切换（trend→range/panic），动态调整仓位")

        if suggestions:
            lines.extend(suggestions)
        else:
            lines.append("- 当前规则运行正常，继续观察")

        return "\n".join(lines)

    @staticmethod
    def _footer() -> str:
        return (
            "---\n"
            "*本报告由 AI Quant Agent 自动生成，仅供研究参考。*\n"
            "*不构成任何投资建议，交易有风险，决策需谨慎。*\n"
            f"*生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*"
        )
