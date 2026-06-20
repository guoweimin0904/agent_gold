"""AI Quant Agent — 全流程一键运行脚本 (主入口).

本脚本是系统的唯一推荐入口 (main.py 已废弃，仅保留做兼容)。

流程:
1. 数据采集       → data/market_snapshot.json
2. 新闻监控       → data/news_report.json
3. 回测           → data/backtest/*.json
4. 评分引擎       → data/scoring_report.json
5. 综合决策       → data/comprehensive_decision.json
6. 风控审查       → data/risk_audit_report.json
7. 执行门         → data/execution_gate_output.json
8. 机会扫描       → data/opportunity_batch.json
9. 日报           → reports/generated/daily_report_*.md

用法:
    python3 run_pipeline.py
"""

import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

# Set execution mode
os.environ["EXECUTION_MODE"] = "paper"
os.environ["ENABLE_REAL_TRADING"] = "false"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "pipeline.log"),
    ],
)
logger = logging.getLogger("pipeline")

ROOT = Path(__file__).parent


def step(label: str, fn):
    """Run a pipeline step with timing."""
    import time
    logger.info("=" * 50)
    logger.info("步骤: %s", label)
    logger.info("=" * 50)
    t0 = time.time()
    try:
        result = fn()
        elapsed = time.time() - t0
        logger.info("✅ %s 完成 (%.1fs)", label, elapsed)
        return result
    except Exception as e:
        elapsed = time.time() - t0
        logger.error("❌ %s 失败 (%.1fs): %s", label, elapsed, e)
        raise


def _compute_indicators_from_klines(klines: list[dict]) -> dict:
    from analysis.indicators import add_all_indicators

    if not klines or len(klines) < 30:
        logger.warning("K线数据不足(%d条)，回退到中性默认指标", len(klines) if klines else 0)
        last_close = float(klines[-1]["close"]) if klines else 0
        return {
            "rsi": 50.0, "macd_hist": 0.0,
            "ema_9": last_close * 0.997 if last_close else None,
            "ema_21": last_close * 0.985 if last_close else None,
            "close": last_close,
            "bb_upper": last_close * 1.04 if last_close else None,
            "bb_lower": last_close * 0.95 if last_close else None,
            "atr": last_close * 0.015 if last_close else None,
        }

    df = pd.DataFrame([{
        "timestamp": k["timestamp"],
        "open": float(k["open"]),
        "high": float(k["high"]),
        "low": float(k["low"]),
        "close": float(k["close"]),
        "volume": float(k.get("volume", 0)),
    } for k in klines])

    try:
        df = add_all_indicators(df)
        last = df.iloc[-1]
        return {
            "rsi": float(last["rsi"]) if pd.notna(last["rsi"]) else 50.0,
            "macd_hist": float(last["macd_hist"]) if pd.notna(last["macd_hist"]) else 0.0,
            "ema_9": float(last["ema_9"]) if pd.notna(last["ema_9"]) else None,
            "ema_21": float(last["ema_21"]) if pd.notna(last["ema_21"]) else None,
            "close": float(last["close"]),
            "bb_upper": float(last["bb_upper"]) if pd.notna(last["bb_upper"]) else None,
            "bb_lower": float(last["bb_lower"]) if pd.notna(last["bb_lower"]) else None,
            "atr": float(last["atr"]) if pd.notna(last["atr"]) else None,
        }
    except Exception as e:
        logger.warning("指标计算失败: %s，回退到中性默认", e)
        latest_price = float(klines[-1]["close"])
        return {
            "rsi": 50.0, "macd_hist": 0.0,
            "ema_9": latest_price * 0.997,
            "ema_21": latest_price * 0.985,
            "close": latest_price,
            "bb_upper": latest_price * 1.04,
            "bb_lower": latest_price * 0.95,
            "atr": latest_price * 0.015,
        }


def _load_klines_for_symbol(symbol: str = "BTCUSDT", source: str = "binance") -> tuple[list[dict], list[dict]]:
    snap_path = ROOT / "data" / "market_snapshot.json"
    klines: list[dict] = []
    overview: list[dict] = []
    if snap_path.exists():
        snap_data = json.loads(snap_path.read_text())
        klines = [k for k in snap_data.get("klines", [])
                  if k.get("source") == source and k.get("symbol") == symbol][:100]
        overview = snap_data.get("market_overview", [])
    return klines, overview


def _load_news_report() -> dict:
    news_path = ROOT / "data" / "news_report.json"
    if news_path.exists():
        return json.loads(news_path.read_text())
    return {}


def main() -> None:
    logger.info("🚀 AI Quant Agent — 全流程启动")

    # ── 1. Data ingestion ───────────────────────────────────────────
    def do_data():
        from data_layer.unified_ingestor import DataIngestor
        snap = DataIngestor().ingest()
        logger.info("  Klines: %d | Overview: %d | News: %d",
                     len(snap.klines), len(snap.market_overview), len(snap.news))
        return snap

    snap = step("1. 数据采集 (Data Ingestion)", do_data)

    # ── 2. News pipeline ────────────────────────────────────────────
    def do_news():
        from news.pipeline import NewsPipeline
        batch = NewsPipeline().run(hours=24, max_items=20)
        logger.info("  新闻报告: %d 条 (S=%d A=%d B=%d C=%d)",
                     len(batch.reports), batch.s_events, batch.a_events,
                     batch.b_events, batch.c_events)
        return batch

    step("2. 新闻监控 (News Pipeline)", do_news)

    # ── 3. Backtest ─────────────────────────────────────────────────
    def do_backtest():
        from backtest.runner import run as run_backtest
        for sym in ["BTCUSDT", "ETHUSDT"]:
            try:
                result = run_backtest(symbol=sym, interval="1h", fee_rate=0.001)
                logger.info("  回测 %s: return=%s%% trades=%d",
                            sym, result.get("total_return_pct"), result.get("trade_count"))
            except Exception as e:
                logger.warning("  回测 %s 失败: %s (可能数据不足)", sym, e)
        return True

    step("3. 回测 (Backtest)", do_backtest)

    # ── 4. Scoring ──────────────────────────────────────────────────
    def do_scoring():
        # Load klines from snapshot
        snap_data = json.loads((ROOT / "data" / "market_snapshot.json").read_text())
        klines = [k for k in snap_data.get("klines", [])
                  if k.get("source") == "binance" and k.get("symbol") == "BTCUSDT"][:100]
        overview = snap_data.get("market_overview", [])
        latest_price = float(klines[-1]["close"]) if klines else 65000

        indicators = {
            "rsi": 45, "macd_hist": 3.2,
            "ema_9": latest_price * 0.997,
            "ema_21": latest_price * 0.985,
            "close": latest_price,
            "bb_upper": latest_price * 1.04,
            "bb_lower": latest_price * 0.95,
            "atr": 850,
        }

        news_report = {}
        news_path = ROOT / "data" / "news_report.json"
        if news_path.exists():
            news_report = json.loads(news_path.read_text())

        from scoring.orchestrator import ScoringOrchestrator
        report = ScoringOrchestrator().score(
            symbol="BTCUSDT",
            timeframe="1h",
            klines=klines,
            latest_indicators=indicators,
            market_overview=overview,
            news_report=news_report,
            risk_status={
                "kill_switch_active": False,
                "daily_loss_limit_hit": False,
                "s_event_active": False,
            },
        )
        logger.info("  评分: final=%.1f decision=%s confidence=%.0f%%",
                     report.final_score, report.decision, report.confidence * 100)
        return report

    step("4. 评分引擎 (Scoring)", do_scoring)

    # ── 5. Comprehensive Decision ──────────────────────────────────
    def do_decision():
        snap_data = json.loads((ROOT / "data" / "market_snapshot.json").read_text())
        klines = [k for k in snap_data.get("klines", [])
                  if k.get("source") == "binance" and k.get("symbol") == "BTCUSDT"][:100]
        overview = snap_data.get("market_overview", [])
        latest_price = float(klines[-1]["close"]) if klines else 65000

        indicators = {
            "rsi": 45, "macd_hist": 3.2,
            "ema_9": latest_price * 0.997,
            "ema_21": latest_price * 0.985,
            "close": latest_price,
            "bb_upper": latest_price * 1.04,
            "bb_lower": latest_price * 0.95,
            "atr": 850,
        }

        news_report = {}
        news_path = ROOT / "data" / "news_report.json"
        if news_path.exists():
            news_report = json.loads(news_path.read_text())

        from llm.comprehensive_decision_agent import ComprehensiveDecisionAgent
        decision = ComprehensiveDecisionAgent().decide(
            symbol="BTCUSDT",
            timeframe="1h",
            klines=klines,
            latest_indicators=indicators,
            market_overview=overview,
            news_report=news_report,
            risk_status={
                "kill_switch_active": False,
                "daily_loss_limit_hit": False,
                "s_event_active": False,
            },
        )
        logger.info("  决策: direction=%s score=%.1f vetoed=%s",
                     decision.direction, decision.final_score, decision.vetoed)
        return decision

    step("5. 综合决策 (Decision)", do_decision)

    # ── 6. Risk Audit ──────────────────────────────────────────────
    def do_audit():
        decision = json.loads((ROOT / "data" / "comprehensive_decision.json").read_text())
        scoring = json.loads((ROOT / "data" / "scoring_report.json").read_text())
        news_report = {}
        news_path = ROOT / "data" / "news_report.json"
        if news_path.exists():
            news_report = json.loads(news_path.read_text())

        from risk.audit_agent import RiskAuditAgent
        report = RiskAuditAgent().audit(
            decision,
            context={
                "risk_status": {
                    "kill_switch_active": False,
                    "daily_loss_limit_hit": False,
                    "s_event_active": False,
                },
                "news_report": news_report,
                "scoring_report": scoring,
                "backtest_result": {},
            },
        )
        logger.info("  风控: approved=%s risk_level=%s",
                     report.approved, report.risk_level)
        return report

    step("6. 风控审查 (Audit)", do_audit)

    # ── 7. Execution Gate ──────────────────────────────────────────
    def do_gate():
        decision = json.loads((ROOT / "data" / "comprehensive_decision.json").read_text())
        audit = json.loads((ROOT / "data" / "risk_audit_report.json").read_text())

        from execution.execution_gate import ExecutionGate
        plan = ExecutionGate().approve(
            decision,
            audit_report=audit,
            validator_passed=True,
            capital=10000.0,
        )
        logger.info("  执行门: approved=%s mode=%s",
                     plan.approved, plan.execution_mode)
        if plan.approved:
            logger.info("  → %s %s %.2f USDT SL:%s",
                        plan.symbol, plan.direction, plan.quantity_usdt, plan.stop_loss)
        else:
            logger.info("  → 不执行: %s", plan.reject_reason[:60])
        return plan

    step("7. 执行门 (Execution Gate)", do_gate)

    # ── 8. Opportunity Scan ────────────────────────────────────────
    def do_opportunity():
        snap_data = json.loads((ROOT / "data" / "market_snapshot.json").read_text())
        klines = [k for k in snap_data.get("klines", [])
                  if k.get("source") == "binance" and k.get("symbol") == "BTCUSDT"][:100]
        overview = snap_data.get("market_overview", [])
        latest_price = float(klines[-1]["close"]) if klines else 65000

        indicators = {
            "rsi": 45, "macd_hist": 3.2,
            "ema_9": latest_price * 0.997,
            "ema_21": latest_price * 0.985,
        }

        from opportunity.orchestrator import OpportunityOrchestrator
        batch = OpportunityOrchestrator().scan_all(
            symbol="BTCUSDT",
            klines=klines,
            indicators=indicators,
            market_overview=overview,
            risk_status={
                "kill_switch_active": False,
                "s_event_active": False,
            },
        )
        logger.info("  机会扫描: %d signals, critical=%d high=%d",
                     batch.total_signals, batch.critical_count, batch.high_count)
        if batch.best_candidate:
            logger.info("  最佳候选: %s", batch.best_candidate)
        return batch

    step("8. 机会扫描 (Opportunity)", do_opportunity)

    # ── 9. Daily Report ────────────────────────────────────────────
    def do_report():
        from reports.daily_report_generator import DailyReportGenerator
        report = DailyReportGenerator().generate(symbol="BTCUSDT", timeframe="1h")
        logger.info("  日报已生成: %d 字符", len(report))
        print("\n" + "=" * 60)
        print(report)
        return report

    step("9. 日报生成 (Report)", do_report)

    logger.info("=" * 50)
    logger.info("🎉 全流程完成！")
    logger.info("查看报告: reports/generated/")
    logger.info("查看数据: data/")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
