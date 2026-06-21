"""A-Share data connector — uses Sina Finance API + AKShare financial abstract.

Working data sources:
- 实时行情: Sina hq.sinajs.cn ✅
- 日K线: Sina money.finance.sina.com.cn ✅
- 基本面: AKShare stock_financial_abstract ✅ (80+财务指标)
- 资金流: 基于K线量价推导 ✅ (替代被代理阻断的EastMoney)
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

import akshare as ak
import requests

logger = logging.getLogger("connectors.ashare")

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {"http": "", "https": ""}
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn",
})


# ── Sina symbol helper ─────────────────────────────────────────────

def _sina_symbol(code: str) -> str:
    if code.startswith("6") or code.startswith("5"):
        return f"sh{code}"
    elif code.startswith("0") or code.startswith("3"):
        return f"sz{code}"
    elif code.startswith("8") or code.startswith("4"):
        return f"bj{code}"
    return f"sh{code}"


# ── Sina Quote ─────────────────────────────────────────────────────

def _parse_sina_quote(data: str) -> dict[str, Any]:
    match = re.search(r'"(.*)"', data)
    if not match:
        return {}
    parts = match.group(1).split(",")
    if len(parts) < 33:
        return {}
    return {
        "name": parts[0],
        "open": float(parts[1]) if parts[1] else 0,
        "close_yest": float(parts[2]) if parts[2] else 0,
        "price": float(parts[3]) if parts[3] else 0,
        "high": float(parts[4]) if parts[4] else 0,
        "low": float(parts[5]) if parts[5] else 0,
        "volume": float(parts[8]) if parts[8] else 0,
        "amount": float(parts[9]) if parts[9] else 0,
        "bid1": float(parts[10]) if parts[10] else 0,
        "ask1": float(parts[12]) if parts[12] else 0,
        "date": parts[30],
        "time": parts[31],
    }


# ── 新浪K线API ────────────────────────────────────────────────────
def _sina_klines(symbol: str, limit: int = 60) -> list[dict[str, Any]]:
    """Fetch K-Line data from Sina Finance API.

    Sina datalen 最大值为1023（约4年日K线）。
    直接用1023保证覆盖任意长度的请求，然后截取需要的数量。
    """
    sina_sym = _sina_symbol(symbol)
    # 用最大 datalen 确保覆盖所有数据
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/jsonp_v2.php/"
           f"var%20_%20=new%20Date().getTime()/CN_MarketData.getKLineData"
           f"?symbol={sina_sym}&scale=240&ma=no&datalen=1023")
    try:
        resp = _SESSION.get(url, timeout=15)
        resp.encoding = "utf-8"
        text = resp.text
        import json as _json
        start = text.index("[")
        end = text.rindex("]") + 1
        data = _json.loads(text[start:end])
        records = []
        for item in data:
            records.append({
                "timestamp": datetime.strptime(item["day"], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc).isoformat(),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": float(item["volume"]),
            })
        # Sina 返回升序（最早在前），不需要反转
        # 截取最后 limit 条（最新数据）
        if len(records) > limit:
            records = records[-limit:]
        logger.info("新浪K线 %s: 返回%d条, 截取%d条", symbol, len(data), len(records))
        return records
    except Exception as e:
        logger.error("新浪K线 %s 失败: %s", symbol, e)
        return []


# ── AKShare 基本面解析 ─────────────────────────────────────────────

_FINANCIAL_CACHE: dict[str, dict[str, Any]] = {}


def _parse_financial_abstract(symbol: str) -> dict[str, Any]:
    """解析 AKShare stock_financial_abstract 为 key-value 结构."""
    if symbol in _FINANCIAL_CACHE:
        return _FINANCIAL_CACHE[symbol]

    result: dict[str, Any] = {}
    try:
        df = ak.stock_financial_abstract(symbol=symbol)
        if df.empty:
            return result
        for _, row in df.iterrows():
            name = str(row.get("指标", "")).strip()
            val_latest = row.get("20260331", "")  # 最新季度
            val_year = row.get("20251231", "")     # 最新年报
            val = val_latest if val_latest and val_latest != "nan" else val_year
            if val and str(val) != "nan":
                try:
                    result[name] = float(val)
                except (ValueError, TypeError):
                    result[name] = val
        _FINANCIAL_CACHE[symbol] = result
        logger.info("基本面 %s: 解析 %d 个指标", symbol, len(result))
    except Exception as e:
        logger.warning("基本面 %s 解析失败: %s", symbol, e)
    return result


# ── 实时行情 ──────────────────────────────────────────────────────

def get_quote_from_sina(code: str) -> dict[str, Any]:
    url = f"https://hq.sinajs.cn/list={_sina_symbol(code)}"
    try:
        resp = _SESSION.get(url, timeout=10)
        resp.encoding = "gbk"
        quote = _parse_sina_quote(resp.text)
        if quote:
            price = quote.get("price", 0)
            yest = quote.get("close_yest", price)
            change_pct = (price - yest) / yest * 100 if yest > 0 else 0
            quote["code"] = code
            quote["change_pct"] = round(change_pct, 2)
            quote["volume"] = quote.get("volume", 0) * 100
        return quote
    except Exception as e:
        logger.error("新浪行情 %s 失败: %s", code, e)
        return {}


def get_spot(symbol: str = "") -> list[dict[str, Any]]:
    if symbol:
        quote = get_quote_from_sina(symbol)
        if quote:
            # 尝试从财务摘要获取PE/PB
            fin = _parse_financial_abstract(symbol)
            price = quote.get("price", 0)
            eps = fin.get("基本每股收益", 0)
            bvps = fin.get("每股净资产", 0)
            if eps and eps > 0 and price > 0:
                quote["pe_ttm"] = round(price / eps, 2)
            if bvps and bvps > 0 and price > 0:
                quote["pb"] = round(price / bvps, 2)
        return [quote] if quote else []
    return []


# ── 历史K线 ────────────────────────────────────────────────────────

def get_klines(
    symbol: str,
    period: str = "daily",
    start_date: str = "",
    end_date: str = "",
    adjust: str = "qfq",
    limit: int = 0,
) -> list[dict[str, Any]]:
    if period in ("daily", "日k", "日"):
        sina_records = _sina_klines(symbol, limit=limit or 60)
        if sina_records:
            return sina_records
    try:
        df = ak.stock_zh_a_hist(symbol=symbol, period=period,
                                start_date=start_date or "20200101",
                                end_date=end_date or datetime.now().strftime("%Y%m%d"),
                                adjust=adjust)
        if limit > 0:
            df = df.tail(limit)
        df = df.rename(columns={"日期": "timestamp", "开盘": "open", "收盘": "close",
                                "最高": "high", "最低": "low", "成交量": "volume",
                                "成交额": "amount", "振幅": "amplitude",
                                "涨跌幅": "change_pct", "涨跌额": "change",
                                "换手率": "turnover"})
        df["timestamp"] = df["timestamp"].apply(
            lambda x: datetime.strptime(str(x), "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat())
        records = df.to_dict(orient="records")
        logger.info("AKShare K线 %s: %d 条", symbol, len(records))
        return records
    except Exception as e:
        logger.error("K线 %s 失败: %s", symbol, e)
        return []


# ── 基本面 ─────────────────────────────────────────────────────────

def get_fundamentals(symbol: str) -> dict[str, Any]:
    """
    获取 A 股基本面数据。

    数据来源: AKShare stock_financial_abstract (已验证可用 ✅)
    包含: ROE, EPS, 毛利率, 净利率, 营收, 净利润, 负债率, 每股净资产等
    """
    fin = _parse_financial_abstract(symbol)
    if not fin:
        return {}

    spot_data = {}
    try:
        spot = get_quote_from_sina(symbol)
        spot_data = spot or {}
    except Exception:
        pass

    price = float(spot_data.get("price", 0))
    eps = fin.get("基本每股收益", 0)
    bvps = fin.get("每股净资产", 0)

    result: dict[str, Any] = {}
    if eps and eps > 0 and price > 0:
        result["pe_ttm"] = round(price / eps, 2)
    if bvps and bvps > 0 and price > 0:
        result["pb"] = round(price / bvps, 2)
    if fin.get("净资产收益率(ROE)"):
        result["roe"] = float(fin["净资产收益率(ROE)"])
    if fin.get("毛利率"):
        result["gross_margin"] = float(fin["毛利率"])
    if fin.get("销售净利率"):
        result["net_margin"] = float(fin["销售净利率"])
    if fin.get("资产负债率"):
        result["debt_ratio"] = float(fin["资产负债率"])
    if fin.get("营业总收入"):
        result["revenue"] = float(fin["营业总收入"])
    if fin.get("归母净利润"):
        result["net_profit"] = float(fin["归母净利润"])
    if fin.get("营业总收入增长率"):
        result["revenue_growth"] = float(fin["营业总收入增长率"])
    if fin.get("归属母公司净利润增长率"):
        result["profit_growth"] = float(fin["归属母公司净利润增长率"])

    logger.info("基本面 %s: PE=%.1f PB=%.1f ROE=%.1f%% 毛利率=%.1f%% 负债率=%.1f%%",
                symbol, result.get("pe_ttm", 0), result.get("pb", 0),
                result.get("roe", 0), result.get("gross_margin", 0),
                result.get("debt_ratio", 0))
    return result


# ── 资金流向(基于K线量价推导) ──────────────────────────────────

def get_fund_flow(symbol: str) -> dict[str, Any]:
    """
    资金流向评分（基于K线量价关系推导）。

    当 EastMoney 资金流 API 不可用时，我们通过量价关系估算:
    - 上涨放量 → 资金流入
    - 下跌缩量 → 资金稳定
    - 下跌放量 → 资金流出
    """
    klines = _sina_klines(symbol, limit=30)
    if len(klines) < 10:
        return {}

    closes = [k["close"] for k in klines[-20:]]
    volumes = [k["volume"] for k in klines[-20:]]
    recent = closes[-5:]
    older = closes[-20:-5]

    # Price-volume correlation
    up_vol = 0
    down_vol = 0
    total_vol = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            up_vol += volumes[i]
        else:
            down_vol += volumes[i]
        total_vol += volumes[i]

    up_ratio = up_vol / total_vol if total_vol > 0 else 0.5

    # Main net inflow estimate (normalized -1 to +1)
    trend = (sum(recent) / len(recent) - sum(older) / len(older))
    trend_norm = trend / (sum(older) / len(older)) if sum(older) > 0 else 0
    main_flow = up_ratio * 2 - 1  # -1 to +1
    main_flow = main_flow * 0.5 + trend_norm * 0.5  # blend with trend

    return {
        "main_net_inflow": round(main_flow * 1e7, 0),  # 模拟金额
        "up_volume_ratio": round(up_ratio, 3),
        "trend_estimate": round(trend_norm, 4),
    }


# ── 市场情绪 ─────────────────────────────────────────────────────

def get_market_sentiment() -> dict[str, Any]:
    return {"sentiment": 50, "note": "全市场数据暂不可用"}
