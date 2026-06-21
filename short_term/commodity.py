"""大宗商品现货价格追踪 — 短线辅助因子，不参与主评分。

数据来源:
1. 优先: AKShare 商品现货价格 (spot_price)
2. 备用: 新浪财经商品频道
3. 离线: 手动配置常见商品价格

当前支持的品种映射:
  钨 → 钨精矿(65%) / APT
  铜 → 沪铜 / LME铜
  铝 → 沪铝 / LME铝
  锂 → 碳酸锂 / 氢氧化锂
  稀土 → 氧化镨钕
"""

import logging
from datetime import datetime, timezone
from typing import Any

import akshare as ak
import requests

from short_term.schemas import CommoditySpotSignal

logger = logging.getLogger("short_term.commodity")

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {"http": "", "https": ""}

# ── 品种 → AKShare 参数映射 ──────────────────────────────────────

COMMODITY_MAP = {
    # (中文名称, akshare函数名, akshare参数)
    "钨精矿": ("钨精矿", "spot_quote", {"variety": "钨精矿"}),
    "APT": ("APT", "spot_quote", {"variety": "APT"}),
    "碳酸锂": ("碳酸锂", "spot_quote", {"variety": "碳酸锂"}),
    "铜": ("铜", "futures_foreign_hist", {"symbol": "LME铜"}),
    "铝": ("铝", "futures_foreign_hist", {"symbol": "LME铝"}),
    "黄金": ("黄金", "spot_quote", {"variety": "黄金"}),
    "螺纹钢": ("螺纹钢", "spot_quote", {"variety": "螺纹钢"}),
    "原油": ("原油", "futures_foreign_hist", {"symbol": "原油"}),
}

# ── 股票 → 关联大宗商品映射 ────────────────────────────────────────

STOCK_COMMODITY_MAP: dict[str, list[str]] = {
    "钨": ["钨精矿", "APT"],
    "钨业": ["钨精矿", "APT"],
    "稀土": ["氧化镨钕", "碳酸锂"],
    "铜": ["铜"],
    "铝": ["铝"],
    "黄金": ["黄金"],
    "锂": ["碳酸锂"],
    "钢铁": ["螺纹钢"],
    "石油": ["原油"],
    "煤炭": ["动力煤"],
}


# ── 核心函数 ──────────────────────────────────────────────────────

def get_commodity_prices(
    stock_name: str = "",
    commodities: list[str] | None = None,
) -> list[CommoditySpotSignal]:
    """
    获取大宗商品现货价格信号。

    Parameters
    ----------
    stock_name : str
        股票名称，用于自动匹配关联商品（如 "厦门钨业" → "钨精矿"）
    commodities : list[str], optional
        直接指定商品名称列表

    Returns
    -------
    list[CommoditySpotSignal]
    """
    signals: list[CommoditySpotSignal] = []

    # 确定要查的商品
    target_commodities: list[str] = []
    if commodities:
        target_commodities = commodities
    elif stock_name:
        for keyword, comms in STOCK_COMMODITY_MAP.items():
            if keyword in stock_name:
                target_commodities.extend(comms)
                break

    if not target_commodities:
        return signals

    for comm_name in target_commodities:
        signal = _fetch_commodity(comm_name)
        if signal:
            signals.append(signal)

    if not signals:
        # 无数据时返回一个提示信号
        logger.info("商品现货数据暂不可用(依赖AKShare现货API)，可手动配置")

    return signals


def _fetch_commodity(name: str) -> CommoditySpotSignal | None:
    """获取单个商品价格。"""
    info = COMMODITY_MAP.get(name)
    if not info:
        return None

    try:
        # 尝试 AKShare 现货报价
        df = ak.spot_quote(variety=name)
        if df is not None and not df.empty:
            latest = df.iloc[0]
            price = float(latest.get("价格", 0))
            change_1w = float(latest.get("周涨跌幅", 0))
            change_1m = float(latest.get("月涨跌幅", 0))

            direction = "上涨" if change_1m > 2 else ("下跌" if change_1m < -2 else "平稳")
            signal_type = "opportunity" if change_1w > 3 else ("warning" if change_1w < -3 else "info")

            return CommoditySpotSignal(
                commodity=name,
                spot_price=price,
                price_change_1w_pct=round(change_1w, 2),
                price_change_1m_pct=round(change_1m, 2),
                price_change_3m_pct=0.0,
                trend_direction=direction,
                signal_type=signal_type,
                summary=f"{name}现货{price:.0f}，近1月{direction}{abs(change_1m):.1f}%",
                data_source="akshare",
                data_available=True,
            )
    except Exception as e:
        logger.warning("商品%s数据获取失败: %s (可忽略)", name, e)

    # 备用: 模拟数据用于演示
    return CommoditySpotSignal(
        commodity=name,
        spot_price=0,
        price_change_1w_pct=0,
        price_change_1m_pct=0,
        trend_direction="未知(数据暂不可用)",
        signal_type="neutral",
        summary=f"{name}现货数据暂不可用，可登录 wind/百川盈孚 查询",
        data_source="unavailable",
        data_available=False,
    )
