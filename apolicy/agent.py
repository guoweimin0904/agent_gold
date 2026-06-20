"""A-Share Policy Understanding Agent.

Not a simple "bullish/bearish" classifier. Instead, it decomposes the
policy's impact path step by step:

1. Source identification       → 国务院/证监会/央行/...
2. Policy level                → 国家级/部委级/地方级/...
3. Policy type                 → 宏观流动性/产业扶持/监管收紧/...
4. Benefit / harm direction    → 受益板块 + 受损板块
5. Time horizon                → 当天/1-5天/1-3月/长期
6. Market reaction assessment  → 未反应/部分反应/充分反应/过度反应
7. Trading score (0-100)       → <60 = not tradeable
8. Verification                → unreliable source → "需要验证，不可交易"
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from apolicy.decision_schemas import (
    Direction,
    MarketReaction,
    PolicyAnalysisReport,
    PolicyLevel,
    PolicyType,
    SourceReliability,
    SourceType,
    TimeHorizon,
)

logger = logging.getLogger("apolicy.agent")

# ── Source keyword maps ─────────────────────────────────────────────

SOURCE_KEYWORDS: dict[SourceType, list[str]] = {
    "国务院": ["国务院", "国常会", "总理", "国发"],
    "证监会": ["证监会", "证监", "上交所", "深交所"],
    "央行": ["央行", "人民银行", "中国人民银行", "逆回购", "降准", "降息"],
    "发改委": ["发改委", "发展改革委"],
    "工信部": ["工信部", "工业和信息化部"],
    "财政部": ["财政部", "财政"],
    "交易所": ["上交所", "深交所", "北交所", "交易所"],
    "地方政府": ["省政府", "市政府", "地方金融", "地方政府"],
    "行业协会": ["协会", "证券业协会", "基金业协会"],
}

TYPE_KEYWORDS: dict[PolicyType, list[str]] = {
    "宏观流动性": ["降准", "降息", "MLF", "LPR", "逆回购", "流动性", "货币政策"],
    "财政刺激": ["特别国债", "专项债", "减税", "财政赤字", "转移支付"],
    "产业扶持": ["补贴", "专项资金", "国产替代", "产业链", "制造业", "新能源",
                   "半导体", "芯片", "集成电路", "电动车", "光伏", "风电"],
    "监管收紧": ["穿透监管", "严格审查", "禁止", "限制", "处罚", "整顿",
                   "减杠杆", "去杠杆", "不得"],
    "资本市场制度": ["注册制", "退市", "并购", "重组", "上市", "做市",
                      "分红", "回购", "减持", "融资"],
    "行业准入": ["准入", "许可", "牌照", "资质", "合格"],
    "税收调整": ["税率", "减税", "免税", "退税", "消费税", "增值税"],
    "土地/房地产": ["房地产", "土地", "住房", "商品房", "保障房", "限购"],
    "科技/创新": ["自主创新", "科技", "AI", "人工智能", "数字经济", "数据要素"],
    "数据/安全": ["网络安全", "数据安全", "隐私", "合规"],
    "对外开放": ["开放", "外资", "准入负面清单", "自贸区", "一带一路"],
}


# ── Scoring weights ────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "source_authority": 25,        # 国家级=25, 部委级=20, 地方级=10
    "policy_clarity": 20,          # 具体措施=20, 方向性=10, 模糊=5
    "market_reaction": 20,         # 未反应=20, 部分=12, 充分=5
    "impact_magnitude": 20,        # 重大=20, 中等=12, 一般=5
    "verification": 15,            # 官方=15, 媒体=8, 传言=0
}


class PolicyAnalysisAgent:
    """
    A-Share policy understanding agent — rule-based 8-step analysis.

    Not a "predict price" tool. It traces the policy → economic →
    market → sector impact path, and assigns a trade-readiness score.
    """

    def analyze(self, title: str, body: str = "", url: str = "") -> PolicyAnalysisReport:
        """
        Run the complete 8-step policy analysis.

        Parameters
        ----------
        title : str
            Policy news title.
        body : str
            Full text or summary of the policy.
        url : str
            Source URL for verification.
        """
        logger.info("Analyzing policy: %s", title[:60])
        combined = f"{title} {body}"

        report = PolicyAnalysisReport(policy_title=title, source_url=url)
        analysis_path: list[str] = []

        # ── Step 1: Source identification ─────────────────────────
        source, source_reliability = self._identify_source(combined, url)
        report.source = source
        report.source_reliability = source_reliability
        analysis_path.append(f"步骤1-来源识别: {source}({source_reliability})")

        # ── Step 2: Policy level ─────────────────────────────────
        level = self._determine_level(source)
        report.policy_level = level
        analysis_path.append(f"步骤2-政策级别: {level}")

        # ── Step 3: Policy type ──────────────────────────────────
        ptype = self._classify_type(combined)
        report.policy_type = ptype
        analysis_path.append(f"步骤3-政策类型: {ptype}")

        # ── Step 4: Direction + beneficiaries/harmed ─────────────
        direction, beneficiaries, harmed = self._determine_impact(
            ptype, combined, level
        )
        report.overall_direction = direction
        report.beneficiaries = [b.to_dict() for b in beneficiaries]
        report.harmed = [h.to_dict() for h in harmed]
        analysis_path.append(
            f"步骤4-影响方向: {direction}({len(beneficiaries)}受益/{len(harmed)}受损)"
        )

        # ── Step 5: Time horizon ─────────────────────────────────
        horizon = self._estimate_time_horizon(ptype, direction, combined)
        report.time_horizon = horizon
        analysis_path.append(f"步骤5-时间周期: {horizon}")

        # ── Step 6: Market reaction ──────────────────────────────
        reaction = self._assess_market_reaction(
            combined, source_reliability, level
        )
        report.market_reaction = reaction
        analysis_path.append(f"步骤6-市场反应: {reaction}")

        # ── Step 7: Trading score ────────────────────────────────
        score, breakdown = self._compute_trading_score(
            source, source_reliability, level, ptype, direction,
            reaction, combined,
        )
        report.trading_score = score
        report.score_breakdown = breakdown
        analysis_path.append(f"步骤7-交易评分: {score:.1f}")

        # ── Step 8: Verification check ────────────────────────────
        need_verify, verify_reason, is_tradeable = self._verification_check(
            source_reliability, score, combined
        )
        report.need_verify = need_verify
        report.verify_reason = verify_reason
        report.is_tradeable = is_tradeable
        analysis_path.append(
            f"步骤8-验证: {'需验证' if need_verify else '已验证'} | "
            f"{'可交易' if is_tradeable else '不可交易'}"
        )

        # ── Summary ──────────────────────────────────────────────
        report.analysis_path = analysis_path
        report.summary = self._generate_summary(
            source, level, ptype, direction, horizon, reaction, score
        )
        report.risk_note = self._generate_risk_note(
            source_reliability, score, direction, level
        )

        logger.info("Analysis complete: score=%.1f, tradeable=%s", score, is_tradeable)
        return report

    # ── Step implementations ────────────────────────────────────────

    @staticmethod
    def _identify_source(text: str, url: str) -> tuple[SourceType, SourceReliability]:
        """Step 1: Identify policy source and reliability."""
        # URL-based reliability
        if "gov.cn" in url:
            rel: SourceReliability = "官方原文"
        elif any(d in url for d in ["xinhuanet", "people.com.cn", "cctv"]):
            rel = "官方摘要"
        elif any(d in url for d in ["eastmoney", "10jqka", "cls.cn", "wallstreetcn"]):
            rel = "媒体报道"
        elif any(d in url for d in ["weibo", "xueqiu", "tieba"]):
            rel = "转载"
        elif not url:
            rel = "无法验证"
        else:
            rel = "媒体报道"

        # Text-based source identification
        text_lower = text.lower()
        for src, keywords in SOURCE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return src, rel

        # Default
        if "知情人士" in text or "据悉" in text or "消息人士" in text:
            return "媒体转载", "传言"
        return "未知来源", rel

    @staticmethod
    def _determine_level(source: SourceType) -> PolicyLevel:
        """Step 2: Determine policy level from source."""
        level_map: dict[SourceType, PolicyLevel] = {
            "国务院": "国家级",
            "证监会": "部委级",
            "央行": "部委级",
            "发改委": "部委级",
            "工信部": "部委级",
            "财政部": "部委级",
            "交易所": "交易所规则",
            "地方政府": "地方级",
            "行业协会": "行业协会倡议",
        }
        return level_map.get(source, "未明确")

    @staticmethod
    def _classify_type(text: str) -> PolicyType:
        """Step 3: Classify policy type by keyword matching."""
        scores: dict[str, int] = {}
        for ptype, keywords in TYPE_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > 0:
                scores[ptype] = count

        if not scores:
            return "其他"

        # Return type with highest keyword match
        best = max(scores, key=scores.get)
        return best  # type: ignore

    @staticmethod
    def _determine_impact(
        ptype: PolicyType, text: str, level: PolicyLevel
    ) -> tuple[Direction, list[Any], list[Any]]:
        """Step 4: Determine overall direction and affected sectors."""
        from apolicy.decision_schemas import AffectedSector

        text_lower = text.lower()
        beneficiaries: list[AffectedSector] = []
        harmed: list[AffectedSector] = []

        # ── Type-based impact mapping ────────────────────────────
        impact_map: dict[PolicyType, tuple[list[AffectedSector], list[AffectedSector]]] = {
            "宏观流动性": (
                [AffectedSector("大金融(银行/券商)", "利好", reason="流动性宽松降低融资成本，提升估值")],
                [],
            ),
            "财政刺激": (
                [AffectedSector("基建/建材", "利好", reason="财政支出增加，基建投资先行"),
                 AffectedSector("消费", "利好", reason="减税/补贴提升居民可支配收入")],
                [AffectedSector("债券市场", "利空", reason="财政赤字扩大，供给压力")],
            ),
            "产业扶持": (
                [AffectedSector("半导体/芯片", "利好", reason="政策资金+国产替代加速"),
                 AffectedSector("新能源", "利好", reason="补贴延续+产业规划明确")],
                [],
            ),
            "监管收紧": (
                [],
                [AffectedSector("金融科技", "利空", reason="合规成本上升，业务受限"),
                 AffectedSector("互联网平台", "利空", reason="反垄断/数据安全监管")],
            ),
            "资本市场制度": (
                [AffectedSector("券商", "利好", reason="交易活跃度提升，注册制利好投行")],
                [AffectedSector("ST/壳资源", "利空", reason="退市制度完善，壳价值下降")],
            ),
            "行业准入": (
                [],
                [AffectedSector("受影响行业", "结构性影响", reason="准入变化需逐行业分析")],
            ),
            "税收调整": (
                [AffectedSector("受益行业", "利好", reason="减税降低企业负担")],
                [AffectedSector("财政依赖行业", "利空", reason="税收调整可能影响政府支出")],
            ),
            "土地/房地产": (
                [],
                [AffectedSector("房地产", "结构性影响", reason="政策方向决定行业走向，需具体分析")],
            ),
            "科技/创新": (
                [AffectedSector("人工智能/数字经济", "利好", reason="技术方向明确，政策资金倾斜")],
                [],
            ),
            "数据/安全": (
                [AffectedSector("网络安全", "利好", reason="合规需求增加")],
                [AffectedSector("互联网平台", "结构性影响", reason="数据合规成本上升")],
            ),
            "对外开放": (
                [AffectedSector("外资偏好板块", "利好", reason="开放政策提升外资流入预期")],
                [],
            ),
        }

        base = impact_map.get(ptype, ([AffectedSector("需具体分析", "中性")], []))
        beneficiaries, harmed = base

        # ── Keyword-based direction override ─────────────────────
        if any(w in text for w in ["严禁", "禁止", "处罚", "整顿", "不得"]):
            # Even if base is利好, keywords suggest tightening
            pass  # base logic stands

        # ── Determine overall direction ──────────────────────────
        if beneficiaries and not harmed:
            direction: Direction = "利好"
        elif harmed and not beneficiaries:
            direction = "利空"
        elif beneficiaries and harmed:
            direction = "结构性影响"
        else:
            direction = "中性"

        return direction, beneficiaries, harmed

    @staticmethod
    def _estimate_time_horizon(
        ptype: PolicyType, direction: Direction, text: str
    ) -> TimeHorizon:
        """Step 5: Estimate time horizon for policy to take effect."""
        # Immediate effect types
        if ptype in ("宏观流动性",):
            return "当天"
        if ptype in ("资本市场制度",):
            if "即日" in text or "当日" in text:
                return "当天"
            return "1-5个交易日"
        if ptype in ("监管收紧",):
            return "1-5个交易日"
        if ptype in ("产业扶持", "科技/创新", "数据/安全"):
            return "1-3个月"
        if ptype in ("财政刺激", "税收调整"):
            return "1-3个月"
        if ptype in ("行业准入", "对外开放", "土地/房地产"):
            return "长期产业趋势"
        return "1-5个交易日"

    @staticmethod
    def _assess_market_reaction(
        text: str, reliability: SourceReliability, level: PolicyLevel
    ) -> MarketReaction:
        """Step 6: Assess whether market has already priced this in."""
        # Key phrases indicating known/expected policy
        if any(w in text for w in ["此前已经", "市场预期", "符合预期", "早有预期"]):
            return "充分反应"
        if any(w in text for w in ["超预期", "意外", "突然", "临时", "紧急"]):
            return "未反应"
        if any(w in text for w in ["延续", "维持", "不变"]):
            return "充分反应"

        # Rumours /转载 → market may have partially reacted
        if reliability in ("转载", "传言"):
            return "部分反应"

        # High-level unexpected announcement
        if level in ("国家级", "部委级") and reliability in ("官方原文", "官方摘要"):
            return "未反应"

        return "部分反应"

    @staticmethod
    def _compute_trading_score(
        source: SourceType,
        reliability: SourceReliability,
        level: PolicyLevel,
        ptype: PolicyType,
        direction: Direction,
        reaction: MarketReaction,
        text: str,
    ) -> tuple[float, list[dict[str, Any]]]:
        """Step 7: Compute trading score (0-100). < 60 = not tradeable."""
        breakdown: list[dict[str, Any]] = []
        score = 0.0

        # ── Source authority (max 25) ────────────────────────────
        auth_scores: dict[SourceType, float] = {
            "国务院": 25, "证监会": 22, "央行": 23, "发改委": 22,
            "工信部": 20, "财政部": 22, "交易所": 15,
            "地方政府": 10, "媒体转载": 5, "行业协会": 8,
        }
        auth = auth_scores.get(source, 5)
        breakdown.append({
            "dimension": "source_authority",
            "score": auth, "max": 25,
            "reason": f"来源{source}({reliability})权重{auth}分",
        })
        score += auth * (25 / 25)

        # ── Policy clarity (max 20) ──────────────────────────────
        if any(w in text for w in ["具体措施", "将实施", "即日起", "明确"]):
            clarity = 20
            reason = "政策措施具体明确"
        elif any(w in text for w in ["研究", "讨论", "考虑", "拟"]):
            clarity = 10
            reason = "政策处研究阶段"
        else:
            clarity = 14
            reason = "方向性表述"
        breakdown.append({
            "dimension": "policy_clarity",
            "score": clarity, "max": 20, "reason": reason,
        })
        score += clarity * (20 / 20)

        # ── Market reaction (max 20) ─────────────────────────────
        react_scores: dict[MarketReaction, float] = {
            "未反应": 20, "部分反应": 12, "充分反应": 5, "过度反应": 0,
        }
        react = react_scores.get(reaction, 10)
        breakdown.append({
            "dimension": "market_reaction",
            "score": react, "max": 20,
            "reason": f"市场{reaction}({react}分)",
        })
        score += react * (20 / 20)

        # ── Impact magnitude (max 20) ────────────────────────────
        magnitude_scores: dict[PolicyLevel, float] = {
            "国家级": 20, "部委级": 15, "地方级": 8,
            "交易所规则": 10, "行业协会倡议": 5,
        }
        magnitude = magnitude_scores.get(level, 5)
        # Bonus for specific policy types
        if ptype in ("宏观流动性", "财政刺激", "产业扶持"):
            magnitude = min(magnitude + 3, 20)
        breakdown.append({
            "dimension": "impact_magnitude",
            "score": magnitude, "max": 20,
            "reason": f"级别{level}+类型{ptype}({magnitude}分)",
        })
        score += magnitude * (20 / 20)

        # ── Verification (max 15) ────────────────────────────────
        verif_scores: dict[SourceReliability, float] = {
            "官方原文": 15, "官方摘要": 13, "媒体报道": 10,
            "转载": 5, "传言": 0, "无法验证": 0,
        }
        verif = verif_scores.get(reliability, 5)
        breakdown.append({
            "dimension": "verification",
            "score": verif, "max": 15,
            "reason": f"来源可靠性{reliability}({verif}分)",
        })
        score += verif * (15 / 15)

        final_score = max(0, min(100, score))
        return final_score, breakdown

    @staticmethod
    def _verification_check(
        reliability: SourceReliability,
        score: float,
        text: str,
    ) -> tuple[bool, str, bool]:
        """
        Step 8: Verification gate.

        Returns (need_verify, verify_reason, is_tradeable).
        """
        reasons: list[str] = []

        # Rule 8a: Unreliable source
        if reliability in ("传言", "无法验证"):
            reasons.append("来源不可靠或信息不完整，需要验证")
            return True, "；".join(reasons), False

        # Rule 8b: Score < 60
        if score < 60:
            reasons.append(f"交易评分{score:.1f} < 60，不得进入交易候选")
            if reliability in ("转载",):
                reasons.append("来源为转载，准确性存疑")
            return True, "；".join(reasons), False

        # Rule 8c: Ambiguous policy
        if any(w in text for w in ["据悉", "知情人士", "消息人士", "或", "可能", "传"]):
            reasons.append("信息不完整或存在不确定性")
            return True, "；".join(reasons), False

        return False, "", True

    @staticmethod
    def _generate_summary(
        source: SourceType, level: PolicyLevel, ptype: PolicyType,
        direction: Direction, horizon: TimeHorizon,
        reaction: MarketReaction, score: float,
    ) -> str:
        """Generate a 1-2 sentence summary."""
        parts = [
            f"[{source}]{level}级{ptype}政策",
        ]
        if direction == "结构性影响":
            parts.append(f"产生结构性影响，存在受益和受损双方向")
        else:
            parts.append(f"方向{direction}")
        parts.append(f"时间周期{horizon}")
        parts.append(f"市场{reaction}")
        parts.append(f"交易评分{score:.1f}")
        return " | ".join(parts)

    @staticmethod
    def _generate_risk_note(
        reliability: SourceReliability,
        score: float,
        direction: Direction,
        level: PolicyLevel,
    ) -> str:
        """Generate risk notes."""
        notes: list[str] = []

        if reliability in ("传言", "无法验证", "转载"):
            notes.append("来源可靠性低，需等待官方确认")

        if score < 60:
            notes.append("评分不足，不可交易")

        if level == "地方级":
            notes.append("地方级政策影响范围有限，关注后续全国推广")

        if direction == "结构性影响":
            notes.append("结构性政策需具体分析受益和受损方向，不可一概而论")

        return "；".join(notes) if notes else "无特殊风险提示"
