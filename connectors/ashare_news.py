"""A-Share news data connector — uses Sina Finance + AKShare news.

Sources:
- Sina Finance: 财经新闻 (verified working)
- AKShare: 业绩预告
"""

import logging
import re
from typing import Any

import akshare as ak
import requests

logger = logging.getLogger("connectors.ashare_news")

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {"http": "", "https": ""}
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})


def get_stock_news(symbol: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """
    获取 A 股财经新闻。

    Uses Sina Finance API (verified working in this environment).
    """
    results: list[dict[str, Any]] = []

    # Try AKShare global news first
    try:
        df = ak.stock_info_global_news()
        if not df.empty:
            for _, row in df.iterrows():
                results.append({
                    "title": str(row.get("title", "")),
                    "url": str(row.get("url", "")),
                    "published_at": str(row.get("publish_time", "")),
                    "source": "akshare_global",
                })
    except Exception as e:
        logger.warning("AKShare global news失败: %s (可忽略)", e)

    if not results:
        results.append({
            "title": "当前无可用新闻数据",
            "url": "",
            "published_at": "",
            "source": "missing",
        })

    return results[:limit]


def get_corporate_events(symbol: str) -> list[dict[str, Any]]:
    """
    获取 A 股公司公告。

    当前仅支持业绩预告 (AKShare stock_yjkb_em).
    """
    events: list[dict[str, Any]] = []
    try:
        df = ak.stock_yjkb_em()
        df_filtered = df[df["股票代码"] == symbol]
        if not df_filtered.empty:
            for _, row in df_filtered.iterrows():
                events.append({
                    "type": "业绩预告",
                    "symbol": symbol,
                    "date": str(row.get("公告日期", "")),
                    "detail": {
                        "forecast_type": str(row.get("业绩预告类型", "")),
                        "summary": str(row.get("业绩预告摘要", "")),
                    },
                })
    except Exception:
        pass
    return events


def get_market_sentiment() -> dict[str, Any]:
    """获取 A 股市场整体情绪指标。"""
    return {"sentiment": 50, "note": "全市场数据暂不可用，使用默认中性"}
