"""Sector mapper — maps stock to sector and evaluates policy linkage.

Uses the apolicy module to check if any active policy affects this sector.
"""

import logging
from typing import Any

from stockpicker.schemas import PolicyLinkage, Sector

logger = logging.getLogger("stockpicker.sector")

# ── Stock code → sector mapping (rule-based) ───────────────────────

# Prefix-based A-share sector mapping
SECTOR_PREFIX_MAP: dict[str, Sector] = {
    "60": "金融",        # 上证主板 — 宽泛
    "00": "消费电子",    # 深证主板
    "30": "新能源",      # 创业板 — 宽泛
    "688": "半导体",     # 科创板 — 宽泛
    "8": "其他",         # 北交所
}

# Keyword-based sector detection
SECTOR_KEYWORDS: dict[Sector, list[str]] = {
    "半导体": ["半导体", "芯片", "集成电路", "封测", "晶圆", "中芯", "华虹"],
    "人工智能": ["人工智能", "AI", "大模型", "算力", "智能", "机器人"],
    "新能源": ["新能源", "锂电池", "宁德", "比亚迪", "亿纬", "赣锋"],
    "光伏": ["光伏", "太阳能", "隆基", "通威", "阳光电源", "晶澳"],
    "风电": ["风电", "金风", "明阳", "运达"],
    "储能": ["储能", "派能", "阳光"],
    "汽车": ["汽车", "整车", "零部件", "华为汽车", "小米汽车"],
    "消费电子": ["消费电子", "手机", "立讯", "歌尔", "京东方", "TCL"],
    "医药": ["医药", "医疗", "恒瑞", "迈瑞", "药明", "康龙"],
    "金融": ["银行", "券商", "保险", "招商银行", "中信", "平安"],
    "地产": ["房地产", "万科", "保利", "招商蛇口", "华润"],
    "基建": ["基建", "建筑", "中铁", "中国交建", "中国电建"],
    "军工": ["军工", "航天", "航发", "中航", "沈飞"],
    "消费": ["消费", "白酒", "茅台", "五粮液", "伊利", "海天"],
    "农业": ["农业", "种植", "牧原", "温氏", "海大"],
    "化工": ["化工", "万华", "华鲁", "恒力", "荣盛"],
    "有色": ["有色", "铜", "铝", "黄金", "紫金", "江西铜业"],
    "煤炭": ["煤炭", "中国神华", "陕西煤业", "中煤"],
    "通信": ["通信", "中兴", "烽火", "光迅", "移动"],
    "计算机": ["计算机", "软件", "用友", "金山", "中软"],
    "传媒": ["传媒", "游戏", "分众", "芒果", "哔哩"],
}

# ── Policy ↔ Sector benefit mapping ────────────────────────────────

POLICY_SECTOR_BENEFIT: dict[str, list[tuple[Sector, str, str]]] = {
    "产业扶持": [
        ("半导体", "直接受益", "国家大基金+国产替代政策明确"),
        ("人工智能", "直接受益", "AI产业规划+算力基建政策"),
        ("新能源", "直接受益", "新能源补贴+产业规划延续"),
        ("光伏", "直接受益", "光伏产业扶持+出口退税"),
        ("储能", "直接受益", "储能专项政策"),
        ("汽车", "间接受益", "汽车消费刺激+新能源车补贴"),
    ],
    "宏观流动性": [
        ("金融", "直接受益", "降准降息降低银行负债成本"),
        ("地产", "间接受益", "流动性宽松降低房企融资成本"),
        ("基建", "间接受益", "宽松环境支持基建投资"),
    ],
    "科技/创新": [
        ("半导体", "直接受益", "科技自立+国产替代"),
        ("人工智能", "直接受益", "AI+数字经济政策"),
        ("计算机", "间接受益", "信创+国产软件替代"),
        ("通信", "间接受益", "5G/6G基础设施建设"),
    ],
    "监管收紧": [
        ("金融", "结构性影响", "监管收紧可能影响创新业务"),
    ],
    "财政刺激": [
        ("基建", "直接受益", "专项债+基建投资"),
        ("消费", "间接受益", "减税/消费券提振"),
    ],
}


class SectorMapper:
    """Map A-share stock to sector and evaluate policy linkage."""

    def map_stock_to_sector(
        self,
        stock_code: str,
        stock_name: str = "",
    ) -> Sector:
        """Map a stock code to its sector."""
        # Try keyword first (more accurate)
        if stock_name:
            for sector, keywords in SECTOR_KEYWORDS.items():
                for kw in keywords:
                    if kw in stock_name:
                        return sector

        # Fallback to code prefix
        for prefix, sector in SECTOR_PREFIX_MAP.items():
            if stock_code.startswith(prefix):
                return sector

        return "其他"

    def evaluate_policy_linkage(
        self,
        stock_code: str,
        stock_name: str = "",
        policy_report: dict[str, Any] | None = None,
    ) -> PolicyLinkage:
        """Evaluate policy linkage for a given stock."""
        sector = self.map_stock_to_sector(stock_code, stock_name)

        if not policy_report:
            return PolicyLinkage(
                sector=sector,
                sector_strength=50,
                policy_alignment=50,
                active_policy="",
                policy_direction="中性",
                benefit_level="无",
            )

        ptype = policy_report.get("policy_type", "")
        pscore = policy_report.get("trading_score", 0)
        direction = policy_report.get("overall_direction", "中性")
        is_tradeable = policy_report.get("is_tradeable", False)

        # Check if this policy type benefits our sector
        benefit_info = POLICY_SECTOR_BENEFIT.get(ptype, [])
        benefit_level = "无"
        benefit_reason = ""

        for b_sector, b_level, b_reason in benefit_info:
            if b_sector == sector:
                benefit_level = b_level
                benefit_reason = b_reason
                break

        # Compute alignment
        if benefit_level == "直接受益":
            alignment = min(95, 50 + pscore * 0.5)
        elif benefit_level == "间接受益":
            alignment = min(80, 40 + pscore * 0.4)
        else:
            alignment = 30

        # Sector strength = alignment weighted by policy score
        sector_strength = alignment * (pscore / 100) if is_tradeable else alignment * 0.5

        return PolicyLinkage(
            sector=sector,
            sector_strength=round(sector_strength, 1),
            policy_alignment=round(alignment, 1),
            active_policy=f"{ptype}({direction})" if ptype else "",
            policy_direction=direction,
            benefit_level=benefit_level,
        )
