"""Stock picker agent — A-share individual stock analysis engine.

Combines:
1. 基本面/估值评分 (value_screener)
2. 技术面评分 (technical_screener)
3. 板块政策联动 (sector_mapper)
4. 资金面 (fund_flow from klines)
5. 新闻舆情 (from news pipeline or apolicy)
→ 综合评分 + 评级 + 交易建议
"""

import json
import logging
from pathlib import Path
from typing import Any

from stockpicker.schemas import (
    PolicyLinkage,
    StockAnalysisReport,
    StockRating,
)
from stockpicker.sector_mapper import SectorMapper
from stockpicker.technical_screener import score_technical
from stockpicker.value_screener import score_fundamental

logger = logging.getLogger("stockpicker.agent")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "stock_analysis.json"


class StockPickerAgent:
    """
    A-Share individual stock analysis agent.

    Usage:
        report = StockPickerAgent().analyze(
            stock_code="600519",
            stock_name="贵州茅台",
            fundamentals={...},
            klines=[...],
            policy_report={...},
        )
    """

    def __init__(self) -> None:
        self.sector_mapper = SectorMapper()

    def analyze(
        self,
        stock_code: str,
        stock_name: str = "",
        current_price: float = 0.0,
        market: str = "主板",
        # Data inputs
        fundamentals: dict[str, Any] | None = None,
        klines: list[dict[str, Any]] | None = None,
        indicators: dict[str, Any] | None = None,
        policy_report: dict[str, Any] | None = None,
        news_sentiment: float = 50.0,
        fund_flow_score: float = 50.0,
    ) -> StockAnalysisReport:
        """Run complete A-share stock analysis."""
        logger.info("Analyzing %s (%s)", stock_code, stock_name or "?")

        # ── 1. Sector mapping + policy linkage ───────────────────
        sector = self.sector_mapper.map_stock_to_sector(stock_code, stock_name)
        policy_linkage = self.sector_mapper.evaluate_policy_linkage(
            stock_code, stock_name, policy_report
        )

        # ── 2. Fundamental / valuation ───────────────────────────
        funda = score_fundamental(fundamentals)

        # ── 3. Technical ─────────────────────────────────────────
        tech = score_technical(klines, indicators)

        # ── 4. Compose composite score (方案B: 新权重) ────────────
        from stockpicker.heat_factor import compute_heat_factor
        heat = compute_heat_factor(klines, composite_score=50.0)

        # 方案B: 短期动量加分（5日涨幅>8%加分）
        short_momentum = 0.0
        if klines and len(klines) >= 5:
            closes_5 = [float(k["close"]) for k in klines[-5:]]
            chg_5d = (closes_5[-1] - closes_5[0]) / closes_5[0] * 100
            if chg_5d > 8:
                short_momentum = min(5, chg_5d * 0.3)  # 最高加5分
            elif chg_5d < -8:
                short_momentum = max(-3, chg_5d * 0.1)  # 跌太多扣分

        composite, reasons, rating, tradeable = self._compose(
            funda_total=funda.total,
            tech_total=tech.total,
            fund_flow=fund_flow_score,
            policy_alignment=policy_linkage.policy_alignment,
            news_sentiment=news_sentiment,
            policy_linkage=policy_linkage,
            short_term_event_score=news_sentiment,
            short_term_momentum_bonus=short_momentum,
        )

        # 方案A: 热度因子（不参与评分，仅辅助标签）
        heat = compute_heat_factor(klines, composite_score=composite)

        # ── 5. Support / resistance levels ───────────────────────
        support, resistance = self._compute_levels(klines)

        # ── 6. Risk note ─────────────────────────────────────────
        risk_note = self._build_risk_note(
            funda, tech, fund_flow_score, policy_linkage
        )

        report = StockAnalysisReport(
            stock_code=stock_code,
            stock_name=stock_name,
            market=market,  # type: ignore
            sector=sector,
            current_price=current_price,
            fundamental=funda,
            technical=tech,
            fund_flow_score=round(fund_flow_score, 1),
            policy_linkage=policy_linkage,
            news_sentiment=round(news_sentiment, 1),
            composite_score=round(composite, 1),
            rating=rating,
            confidence=round(min(composite / 100, 0.9), 2),
            reason_summary=reasons,
            support_level=support,
            resistance_level=resistance,
            risk_note=risk_note,
            is_tradeable=tradeable,
            # 方案A: 热度因子
            heat_factor=heat.to_dict(),
            # 方案B: 短期评分
            short_term_momentum_bonus=round(short_momentum, 1),
            short_term_event_score=round(news_sentiment, 1),
        )
        # ── Save ──────────────────────────────────────────────────
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report.to_json())
        logger.info("Stock analysis saved to %s", REPORT_PATH)

        self._print(report)
        return report

    # ── AKShare 便捷方法 ──────────────────────────────────────────

    def analyze_from_akshare(
        self,
        stock_code: str,
        stock_name: str = "",
        period: str = "daily",
        days: int = 60,
        policy_report: dict[str, Any] | None = None,
    ) -> StockAnalysisReport:
        """
        使用 AKShare 实时数据鉴股。

        自动获取:
        - 实时行情 (价格、涨跌幅、PE、PB)
        - 历史K线 (用于技术分析)
        - 基本面 (ROE、增长率、负债率)
        - 资金流向

        Parameters
        ----------
        stock_code : str
            6位A股代码。
        stock_name : str, optional
            股票名称，留空则从 AKShare 获取。
        period : str
            "daily" / "weekly" / "monthly"。
        days : int
            拉取多少天的K线。
        policy_report : dict, optional
            PolicyAnalysisReport，影响板块政策联动评分。
        """
        from connectors.ashare import (
            get_fundamentals as ak_fundamentals,
            get_fund_flow as ak_fund_flow,
            get_klines as ak_klines,
            get_spot as ak_spot,
        )
        import requests as _requests

        logger.info("AKShare 鉴股: %s", stock_code)

        # 1. 实时行情 (Sina)
        spot_data = ak_spot(symbol=stock_code)
        spot = spot_data[0] if spot_data else {}
        code = str(spot.get("code", stock_code))
        name = stock_name or str(spot.get("name", ""))
        price = float(spot.get("price", 0))
        # Sina 行情不含 PE/PB，尝试从 EastMoney 获取
        pe_ttm = None
        pb = None
        if price > 0:
            try:
                # EastMoney individual stock query (push2.eastmoney.com, verified working)
                market = "1" if code.startswith("6") else "0"
                em_url = "https://push2.eastmoney.com/api/qt/stock/get"
                em_params = {"secid": f"{market}.{code}", "fields": "f12,f14,f9,f23,f20,f21",
                             "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2}
                em_resp = _requests.get(em_url, params=em_params, timeout=5)
                if em_resp.status_code == 200:
                    em_data = em_resp.json().get("data", {})
                    if em_data:
                        pe_ttm = float(em_data["f9"]) if em_data.get("f9") and float(em_data["f9"]) > 0 else None
                        pb = float(em_data["f23"]) if em_data.get("f23") and float(em_data["f23"]) > 0 else None
            except Exception:
                pass
        turnover = float(spot.get("turnover", 0))
        amount = float(spot.get("amount", 0))

        # 2. K线数据
        klines = ak_klines(symbol=code, period=period, start_date="", end_date="")
        recent_klines = klines[-days:] if len(klines) > days else klines

        # 3. 技术指标
        indicators = {}
        if recent_klines:
            closes = [float(k["close"]) for k in recent_klines[-20:]]
            if len(closes) >= 20:
                indicators["ema_5"] = sum(closes[-5:]) / 5
                indicators["ema_20"] = sum(closes[-20:]) / 20
                # RSI approximation
                gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
                losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
                avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else 0
                avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else 1
                if avg_loss > 0:
                    indicators["rsi"] = 100 - 100 / (1 + avg_gain / avg_loss)
                else:
                    indicators["rsi"] = 70
                indicators["macd_hist"] = (closes[-1] - closes[-5]) / closes[-5] * 10
                bb_center = sum(closes[-20:]) / 20
                bb_std = (sum((c - bb_center)**2 for c in closes[-20:]) / 20)**0.5
                indicators["bb_upper"] = bb_center + 2 * bb_std
                indicators["bb_lower"] = bb_center - 2 * bb_std

        # 4. 基本面 (优先使用 get_fundamentals 返回的 PE/PB)
        fundamentals_raw = ak_fundamentals(code)
        # 使用 get_fundamentals 返回的 PE/PB（来自财务摘要数据）
        fd_pe = fundamentals_raw.get("pe_ttm")
        fd_pb = fundamentals_raw.get("pb")
        fundamentals = {
            "pe_ttm": fd_pe if fd_pe and fd_pe > 0 else (pe_ttm if pe_ttm and pe_ttm > 0 else None),
            "pb": fd_pb if fd_pb and fd_pb > 0 else (pb if pb and pb > 0 else None),
            "roe": fundamentals_raw.get("roe"),
            "revenue_growth_pct": fundamentals_raw.get("revenue_growth"),
            "profit_growth_pct": fundamentals_raw.get("profit_growth"),
            "debt_to_asset_pct": fundamentals_raw.get("debt_ratio"),
            "dividend_yield_pct": None,
            "market_cap": float(spot.get("market_cap", 0)) if spot.get("market_cap") else None,
        }

        # 5. 资金流向
        fund_flow_raw = ak_fund_flow(code)
        main_net = fund_flow_raw.get("main_net_inflow", 0)
        # Score 0-100 based on net inflow (normalized)
        if isinstance(main_net, (int, float)):
            fund_score = 50 + min(30, max(-30, main_net / 1e7 * 10))
        else:
            fund_score = 50

        # 6. 板块确定
        market_type = "科创板" if code.startswith("688") else \
                      "创业板" if code.startswith("30") else \
                      "北交所" if code.startswith("8") else "主板"

        # 7. 市场情绪
        from connectors.ashare_news import get_market_sentiment
        sentiment_data = get_market_sentiment()
        news_sentiment = sentiment_data.get("sentiment", 50)

        # 8. 执行分析
        return self.analyze(
            stock_code=code,
            stock_name=name,
            current_price=price,
            market=market_type,
            fundamentals=fundamentals,
            klines=recent_klines,
            indicators=indicators,
            policy_report=policy_report,
            news_sentiment=news_sentiment,
            fund_flow_score=round(fund_score, 1),
        )

    @staticmethod
    def _compose(
        funda_total: float,
        tech_total: float,
        fund_flow: float,
        policy_alignment: float,
        news_sentiment: float,
        policy_linkage: PolicyLinkage,
        # 新增短期事件舆情评分 (方案B)
        short_term_event_score: float = 50.0,
        # 新增短线动量加分 (方案B)
        short_term_momentum_bonus: float = 0.0,
    ) -> tuple[float, list[str], StockRating, bool]:
        """
        方案B优化: 微调权重适配A股题材行情.

        原权重 (版本1):    基础30% 技术25% 资金15% 政策20% 新闻10%
        新权重 (方案B):    基础30% 技术25% 资金15% 政策15% 长期新闻5% 短期事件5%
        """
        reasons: list[str] = []

        # ── 方案B: 拆分新闻为长期产业新闻 + 短期事件消息 ──
        long_news_weight = 0.05    # 长期产业新闻权重 (原10%拆分为两个5%)
        short_event_weight = 0.05  # 短期事件消息权重
        w_funda = 0.30
        w_tech = 0.25
        w_fund = 0.15
        w_policy = 0.15            # 方案B: 20% → 15%
        w_long_news = long_news_weight
        w_short_event = short_event_weight

        composite = (
            funda_total * w_funda +
            tech_total * w_tech +
            fund_flow * w_fund +
            policy_alignment * w_policy +
            news_sentiment * w_long_news +
            short_term_event_score * w_short_event
        )

        # ── 方案B: 短期动量加分 ──
        if short_term_momentum_bonus > 0:
            composite += short_term_momentum_bonus
            reasons.append(f"短线动量加分(+{short_term_momentum_bonus:.0f})")
            w_tech_effective = w_tech + 0.03  # 技术面等效权重提升
        else:
            w_tech_effective = w_tech

        # Bonus for direct policy benefit
        if policy_linkage.benefit_level == "直接受益" and policy_linkage.policy_alignment > 60:
            composite += 5
            reasons.append(f"政策直接受益({policy_linkage.active_policy})")

        composite = max(5, min(98, composite))

        # Build reasons
        if funda_total >= 70:
            reasons.append(f"基本面良好({funda_total:.0f}分)")
        elif funda_total < 40:
            reasons.append(f"基本面偏弱({funda_total:.0f}分)")

        if tech_total >= 70:
            reasons.append(f"技术面强势({tech_total:.0f}分)")
        elif tech_total < 40:
            reasons.append(f"技术面偏弱({tech_total:.0f}分)")

        if fund_flow >= 65:
            reasons.append(f"资金流入({fund_flow:.0f}分)")
        elif fund_flow < 40:
            reasons.append(f"资金流出({fund_flow:.0f}分)")

        if policy_alignment >= 65:
            reasons.append(f"政策契合({policy_alignment:.0f}分)")

        # Rating
        if composite >= 80:
            rating: StockRating = "强烈推荐"
            tradeable = True
        elif composite >= 70:
            rating = "推荐"
            tradeable = True
        elif composite >= 55:
            rating = "关注"
            tradeable = False  # wait for more signals
        elif composite >= 35:
            rating = "中性"
            tradeable = False
        else:
            rating = "回避"
            tradeable = False

        return composite, reasons, rating, tradeable

    @staticmethod
    def _compute_levels(
        klines: list[dict[str, Any]] | None,
    ) -> tuple[str, str]:
        """Compute support and resistance levels from klines."""
        if not klines or len(klines) < 10:
            return "N/A", "N/A"

        closes = [float(k["close"]) for k in klines[-10:]]
        highs = [float(k["high"]) for k in klines[-10:]]
        lows = [float(k["low"]) for k in klines[-10:]]
        recent = closes[-1]

        res = max(highs)
        sup = min(lows)

        # Round to meaningful levels
        def fmt_level(v: float) -> str:
            if v > 100:
                return f"{v:.0f}"
            elif v > 10:
                return f"{v:.1f}"
            return f"{v:.2f}"

        # Nearest levels
        support_str = fmt_level(sup)
        resist_str = fmt_level(res)

        # If too close, widen
        if (res - sup) / recent < 0.02:
            return fmt_level(recent * 0.95), fmt_level(recent * 1.05)

        return support_str, resist_str

    @staticmethod
    def _build_risk_note(
        funda: Any, tech: Any, fund_flow: float, policy: PolicyLinkage,
    ) -> str:
        """Build risk notes."""
        notes: list[str] = []

        if funda.total < 40:
            notes.append("基本面风险（估值偏高/盈利下滑）")
        if tech.total < 35:
            notes.append("技术面风险（趋势向下/量能不足）")
        if fund_flow < 35:
            notes.append("资金流出风险")
        if policy.benefit_level == "无":
            notes.append("无政策支撑")

        if not notes:
            return "当前无明显风险信号"

        return "；".join(notes)

    @staticmethod
    def _print(report: StockAnalysisReport) -> None:
        print(f"\n─── 鉴股报告: {report.stock_name}({report.stock_code}) ───")
        print(f"板块: {report.sector} | 市场: {report.market} | 现价: {report.current_price}")
        print(f"综合评分: {report.composite_score} | 评级: {report.rating}")
        print(f"可交易: {'✅' if report.is_tradeable else '🛑'} | 信心: {report.confidence:.0%}")
        print(f"\n基本面: {report.fundamental.total:.1f}")
        print(f"  PE={report.fundamental.pe_score:.0f} PB={report.fundamental.pb_score:.0f} "
              f"ROE={report.fundamental.roe_score:.0f} 增长={report.fundamental.growth_score:.0f}")
        print(f"  负债={report.fundamental.debt_score:.0f} 分红={report.fundamental.dividend_score:.0f}")
        print(f"技术面: {report.technical.total:.1f}")
        print(f"  趋势={report.technical.trend_score:.0f} 动量={report.technical.momentum_score:.0f} "
              f"量能={report.technical.volume_score:.0f} 支撑={report.technical.support_resist:.0f}")
        print(f"资金流: {report.fund_flow_score:.0f}")
        print(f"政策联动: {report.policy_linkage.benefit_level} "
              f"(alignment={report.policy_linkage.policy_alignment:.0f})")
        print(f"支撑: {report.support_level} | 阻力: {report.resistance_level}")
        print(f"风控提示: {report.risk_note}")
        # 方案A: 热度因子
        hf = report.heat_factor
        if hf:
            print(f"\n🔥 方案A-热度辅助: {hf.get('heat_label','')} (score={hf.get('heat_score','')})")
            print(f"  {hf.get('summary','')}")
        # 方案B: 短期加分
        if report.short_term_momentum_bonus != 0:
            print(f"⚡ 方案B-短期动量加分: {report.short_term_momentum_bonus:+.1f}")
        if report.reason_summary:
            print("\n理由:")
            for r in report.reason_summary:
                print(f"  • {r}")
        print()
