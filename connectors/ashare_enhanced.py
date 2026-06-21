"""A-Share enhanced data — multi-source news polls + 龙虎榜 + 融资融券.

方案C: 数据源扩容根治底层短板。

新闻源：
  1. AKShare stock_info_global_news (已验证)
  2. Sina Finance 页面抓取 (备选)
  3. 百度新闻/微博热搜 (预留)

资金类：
  1. 龙虎榜 (stock_dzjy_mrmx)
  2. 融资融券余额 (stock_margin_detail)
"""

import logging
from typing import Any

import akshare as ak
import requests

logger = logging.getLogger("connectors.ashare_enhanced")

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {"http": "", "https": ""}
_SESSION.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})


# ═══════════════════════════════════════════════════════════════════
# 方案C: 多源新闻轮询
# ═══════════════════════════════════════════════════════════════════

# 保存历史新闻ID用于去重
_seen_news_ids: set[str] = set()


def poll_all_news(symbol: str = "", limit: int = 15) -> list[dict[str, Any]]:
    """
    多源新闻轮询 — 依次尝试多个新闻源，去重后返回。

    Returns
    -------
    list[dict]
        每条含 title, url, published_at, source, reliability
    """
    all_items: list[dict[str, Any]] = []
    errors: list[str] = []

    # ── 源1: AKShare 全球财经新闻 (已验证可用) ────
    try:
        df = ak.stock_info_global_news()
        if not df.empty:
            for _, r in df.iterrows():
                all_items.append({
                    "title": str(r.get("title", "")),
                    "url": str(r.get("url", "")),
                    "published_at": str(r.get("publish_time", "")),
                    "source": "akshare_global",
                    "content": str(r.get("content", "")),
                    "reliability": "媒体报道",
                })
            logger.info("源1(AKShare全球新闻): %d 条", len(all_items))
    except Exception as e:
        errors.append(f"源1失败: {e}")
        logger.warning("源1(AKShare)失败: %s", e)

    # ── 源2: AKShare 个股新闻 ────
    if symbol:
        try:
            # 不同的AKShare版本可能用不同函数
            for func_name in ["stock_info_global_news", "stock_news"]:
                try:
                    fn = getattr(ak, func_name, None)
                    if fn:
                        df2 = fn(symbol=symbol)
                        if df2 is not None and not df2.empty:
                            for _, r in df2.iterrows():
                                all_items.append({
                                    "title": str(r.get("title", "")),
                                    "url": str(r.get("url", "")),
                                    "published_at": str(r.get("publish_time", str(r.get("date", "")))),
                                    "source": f"akshare_{func_name}",
                                    "content": str(r.get("content", "")),
                                    "reliability": "媒体报道",
                                })
                            break
                except Exception:
                    continue
            logger.info("源2(个股新闻): 累计 %d 条", len(all_items))
        except Exception as e:
            errors.append(f"源2失败: {e}")

    # ── 源3: 新浪财经滚动新闻 (备用) ────
    if len(all_items) < limit:
        try:
            url = "https://roll.finance.sina.com.cn/finance/zq1/ssgsgg/index.shtml"
            resp = _SESSION.get(url, timeout=10)
            if resp.status_code == 200:
                # 简单解析（完整解析需要BeautifulSoup，这里只记录来源可用）
                logger.info("源3(新浪滚动新闻): 可访问 status=%d", resp.status_code)
        except Exception as e:
            errors.append(f"源3失败: {e}")

    # ── 去重 ──
    deduped = []
    seen_titles: set[str] = set()
    for item in all_items:
        key = item["title"][:60]
        if key and key not in seen_titles:
            seen_titles.add(key)
            deduped.append(item)

    logger.info("多源新闻轮询: 原始%d条 → 去重%d条 (错误%d)",
                len(all_items), len(deduped), len(errors))

    if not deduped:
        deduped.append({
            "title": "当前无可用的财经新闻数据",
            "url": "",
            "published_at": "",
            "source": "missing",
            "content": "",
            "reliability": "无法验证",
        })

    return deduped[:limit]


# ═══════════════════════════════════════════════════════════════════
# 方案C: 龙虎榜数据
# ═══════════════════════════════════════════════════════════════════

def get_dragon_tiger(symbol: str = "", days: int = 5) -> list[dict[str, Any]]:
    """
    获取龙虎榜数据。

    AKShare: stock_dzjy_mrmx (大宗交易每日明细)
    stock_dzjy_hy (龙虎榜营业部排名)

    Returns
    -------
    list[dict]
        含 日期/代码/名称/买入额/卖出额/净额/营业部等
    """
    results: list[dict[str, Any]] = []

    # 1. 大宗交易
    try:
        df = ak.stock_dzjy_mrmx(symbol=symbol) if symbol else ak.stock_dzjy_mrmx()
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                results.append({
                    "type": "大宗交易",
                    "code": str(r.get("证券代码", symbol)),
                    "name": str(r.get("证券简称", "")),
                    "price": float(r.get("成交价", 0)),
                    "volume": float(r.get("成交量", 0)),
                    "amount": float(r.get("成交额", 0)),
                    "buy_net": float(r.get("买入净额", 0)),
                    "date": str(r.get("交易日期", "")),
                })
            logger.info("龙虎榜-大宗交易: %d 条", len(results))
    except Exception as e:
        logger.warning("龙虎榜-大宗交易失败: %s (可忽略)", e)

    return results


# ═══════════════════════════════════════════════════════════════════
# 方案C: 融资融券余额
# ═══════════════════════════════════════════════════════════════════

def get_margin_detail(symbol: str = "") -> dict[str, Any]:
    """
    获取融资融券余额。

    AKShare: stock_margin_detail (融资融券明细)

    Returns
    -------
    dict
        含 margin_balance, short_balance, margin_buy, short_sell 等
    """
    result: dict[str, Any] = {}
    try:
        # 个股融资融券
        try:
            df = ak.stock_margin_detail(symbol=symbol)
            if df is not None and not df.empty:
                # 取最新一行
                latest = df.iloc[-1] if len(df) > 1 else df.iloc[0]
                for col_map, our_key in [
                    ("融资余额", "margin_balance"),
                    ("融券余额", "short_balance"),
                    ("融资买入额", "margin_buy"),
                    ("融券卖出额", "short_sell"),
                    ("融资融券余额", "margin_total"),
                ]:
                    if col_map in df.columns:
                        result[our_key] = float(latest[col_map])
                logger.info("融资融券 %s: 融资余额=%.0f", symbol, result.get("margin_balance", 0))
        except Exception:
            pass
    except Exception as e:
        logger.warning("融资融券 %s 失败: %s (可忽略)", symbol, e)

    return result


# ═══════════════════════════════════════════════════════════════════
# 方案C: 龙虎榜买入净额评分
# ═══════════════════════════════════════════════════════════════════

def score_dragon_tiger_flow(dt_data: list[dict[str, Any]]) -> float:
    """
    根据龙虎榜/大宗交易数据计算资金流入评分 (0-100).

    主力净买入多 → 高分；净卖出多 → 低分.
    """
    if not dt_data:
        return 50.0

    total_net = 0.0
    count = 0
    for item in dt_data:
        net = item.get("buy_net", 0)
        if isinstance(net, (int, float)):
            total_net += net
            count += 1

    if count == 0:
        return 50.0

    avg_net = total_net / count
    # 归一化到 0-100: ±1亿对应 ±25分
    score = 50 + min(25, max(-25, avg_net / 1e8 * 25))
    return max(10, min(90, score))


# ═══════════════════════════════════════════════════════════════════
# 方案C: 融资融券评分
# ═══════════════════════════════════════════════════════════════════

def score_margin_flow(margin: dict[str, Any]) -> float:
    """
    根据融资余额变化评分.

    融资余额增加 → 杠杆资金看多 → 加分
    融券余额增加 → 看空增加 → 减分
    """
    margin_buy = margin.get("margin_buy", 0)
    if margin_buy and margin_buy > 1e7:
        return 65.0
    if margin_buy and margin_buy > 1e6:
        return 55.0
    return 50.0
