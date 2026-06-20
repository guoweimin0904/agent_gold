"""多新闻源轮询容错采集 — 四级降级: AKShare(主) → Tushare(备用) → RSSHub(兜底) → 本地缓存/测试数据(最后保障).

设计原则:
1. 任一源成功即返回新闻数据，全部失败绝不返回 missing
2. 内置异常捕获、请求延时、日志埋点，兼容现有快照输出逻辑
3. 输出统一为 connectors.base.NewsItem 列表，与现有 DataIngestor 无缝对接
4. 依赖全为可选导入 — 未安装的源自动降级跳过
5. 最终级：本地JSON缓存 + 内置测试数据，保证永不missing

配置项 (通过 .env 设置):
    TUSHARE_TOKEN       — Tushare Pro API token (不设则跳过 Tushare)
    RSSHUB_URL           — RSSHub 服务地址 (默认 http://127.0.0.1:1200)
    RSSHUB_FEED_PATH     — RSSHub 路由 (默认 /feed/eastmoney/news/global)
"""

import json as _json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from config import BASE_DIR

logger = logging.getLogger("NewsCollector")

# ── 本地缓存路径 ────────────────────────────────────────────────────
NEWS_CACHE_PATH = BASE_DIR / "data" / "news_cache.json"

# ── 可选导入 ────────────────────────────────────────────────────────
try:
    import akshare as ak  # noqa: F811
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    ak = None  # type: ignore
    logger.warning("akshare 未安装，AKShare 数据源不可用。 pip install akshare")

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None  # type: ignore

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    feedparser = None  # type: ignore

try:
    import requests as req
except ImportError:
    req = None  # type: ignore


# ── 配置 (从 config / 环境变量) ──────────────────────────────────────
import os

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
RSSHUB_URL = os.getenv("RSSHUB_URL", "http://127.0.0.1:1200")
RSSHUB_FEED_PATH = os.getenv("RSSHUB_FEED_PATH", "/feed/eastmoney/news/global")

REQUEST_SLEEP_MIN = float(os.getenv("NEWS_REQUEST_SLEEP_MIN", "1"))
REQUEST_SLEEP_MAX = float(os.getenv("NEWS_REQUEST_SLEEP_MAX", "3"))


class MultiSourceNewsCollector:
    """三级数据源轮询新闻采集器.

    采集顺序: AKShare → Tushare → RSSHub.
    任一源成功即返回，全部失败返回空列表。
    """

    def __init__(self) -> None:
        self._available_sources: list[str] = []

        # ── Tushare 初始化 ────────────────────────────────────────
        self._pro = None
        if TUSHARE_AVAILABLE and ts and TUSHARE_TOKEN:
            try:
                ts.set_token(TUSHARE_TOKEN)
                self._pro = ts.pro_api()
                self._available_sources.append("tushare")
                logger.info("Tushare 初始化成功")
            except Exception as e:
                logger.warning("Tushare 初始化失败: %s", e)
        elif not TUSHARE_TOKEN:
            logger.info("未配置 TUSHARE_TOKEN，Tushare 备用数据源不可用")

        # ── AKShare ──────────────────────────────────────────────
        if AKSHARE_AVAILABLE and ak:
            self._available_sources.append("akshare")
            logger.info("AKShare 可用")
        else:
            logger.info("akshare 未安装，AKShare 数据源不可用")

        # ── RSSHub ───────────────────────────────────────────────
        if FEEDPARSER_AVAILABLE and req and feedparser:
            self._available_sources.append("rsshub")
            logger.info("RSSHub 可用 (%s)", RSSHUB_URL + RSSHUB_FEED_PATH)
        else:
            logger.info("feedparser/requests 未安装，RSSHub 兜底数据源不可用")

    # ── 公共 API ────────────────────────────────────────────────────

    def fetch_all(self) -> Union[list[dict], str]:
        """轮询四级数据源，有数据直接返回。全部公网失效时使用本地缓存或测试数据.

        Returns:
            list[dict]: 标准化新闻列表
            \"missing\": 仅当本地缓存也不存在时才返回 (极端情况)
        """
        from connectors.base import NewsItem

        items: list[NewsItem] = []
        self._failure_log: list[str] = []  # 记录每级失败原因

        # 1. AKShare (主)
        news = self._fetch_akshare_news()
        if news:
            items = self._normalize_news_items(news, "akshare")
            logger.info("新闻采集: AKShare 主源命中 %d 条", len(items))
            self._save_cache(items)
            return [it.to_dict() for it in items]
        self._failure_log.append("AKShare 不可用/无数据/超时")

        # 2. Tushare (备用)
        news = self._fetch_tushare_news()
        if news:
            items = self._normalize_news_items(news, "tushare")
            logger.info("新闻采集: Tushare 备用源命中 %d 条", len(items))
            self._save_cache(items)
            return [it.to_dict() for it in items]
        self._failure_log.append("Tushare 不可用 (未配Token/积分耗尽/无数据)")

        # 3. RSSHub (兜底)
        news = self._fetch_rsshub_news()
        if news:
            items = self._normalize_news_items(news, "rsshub")
            logger.info("新闻采集: RSSHub 兜底源命中 %d 条", len(items))
            self._save_cache(items)
            return [it.to_dict() for it in items]
        self._failure_log.append("RSSHub 不可达 (未部署Docker/服务未启动)")

        # 4. 本地缓存 (最后保障)
        cached = self._load_cache()
        if cached:
            logger.warning(
                "三级公网数据源全部失效 (%s)，使用本地缓存 (%d条)",
                ", ".join(self._failure_log), len(cached),
            )
            return cached

        # 5. 内置测试数据 (极端兜底)
        logger.error(
            "全部数据源失效 (%s)，本地缓存也无数据，使用内置测试数据",
            ", ".join(self._failure_log),
        )
        fallback = self._builtin_fallback()
        return [it.to_dict() for it in fallback]

    # ── 三级数据源实现 ───────────────────────────────────────────────

    def _fetch_akshare_news(self) -> Optional[list[dict]]:
        """主数据源: AKShare 东方财富财经新闻 (15秒超时)."""
        if not AKSHARE_AVAILABLE or not ak:
            return None
        try:
            self._random_sleep()
            import signal

            def _timeout_handler(signum, frame):
                raise TimeoutError("AKShare API call timeout")

            try:
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(15)
                df = ak.stock_news_em()
                signal.alarm(0)
            except (ValueError, AttributeError):
                df = ak.stock_news_em()

            if df is None or (hasattr(df, "empty") and df.empty):
                logger.info("AKShare 无新闻数据")
                return None
            news_list = df.to_dict("records")
            logger.info("AKShare 获取新闻 %d 条", len(news_list))
            return news_list
        except Exception as e:
            logger.error("AKShare 采集失败: %s", e)
            return None

    def _fetch_tushare_news(self) -> Optional[list[dict]]:
        """备用数据源: Tushare 财经头条."""
        if not self._pro:
            return None
        try:
            self._random_sleep()
            df = self._pro.news_headline(start_date=time.strftime("%Y%m%d"))
            if df is None or (hasattr(df, "empty") and df.empty):
                logger.info("Tushare 无新闻数据/积分耗尽")
                return None
            news_list = df.to_dict("records")
            logger.info("Tushare 获取新闻 %d 条", len(news_list))
            return news_list
        except Exception as e:
            logger.error("Tushare 采集失败: %s", e)
            return None

    def _fetch_rsshub_news(self) -> Optional[list[dict]]:
        """兜底数据源: RSSHub 东方财富RSS，无调用额度限制."""
        if not FEEDPARSER_AVAILABLE or not feedparser or not req:
            return None
        try:
            self._random_sleep()
            feed_url = RSSHUB_URL.rstrip("/") + RSSHUB_FEED_PATH
            resp = req.get(feed_url, timeout=10)
            if resp.status_code != 200:
                logger.error("RSSHub 返回 HTTP %d", resp.status_code)
                return None
            feed = feedparser.parse(resp.text)
            entries = feed.get("entries", [])
            if not entries:
                logger.info("RSSHub 无新闻条目")
                return None
            news_list = []
            for item in entries:
                news_list.append({
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "published": item.get("published", ""),
                    "link": item.get("link", ""),
                    "source": "eastmoney_rss",
                })
            logger.info("RSSHub 获取新闻 %d 条", len(news_list))
            return news_list
        except Exception as e:
            logger.error("RSSHub 采集失败: %s", e)
            return None

    # ── 内部辅助 ─────────────────────────────────────────────────────

    @staticmethod
    def _random_sleep() -> None:
        """随机延时防反爬."""
        time.sleep(random.uniform(REQUEST_SLEEP_MIN, REQUEST_SLEEP_MAX))

    @staticmethod
    def _normalize_news_items(
        raw_list: list[dict],
        source_type: str,
    ) -> list:
        """将不同源的原始字典统一为 NewsItem 列表.

        适配 AKShare/Tushare 的 pandas row dict 和 RSSHub 的 feed dict.
        """
        from connectors.base import NewsItem

        items: list[NewsItem] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for raw in raw_list:
            # 提取标题 — 不同源的字段名不同
            title = (
                raw.get("title")
                or raw.get("headline")
                or raw.get("news_title")
                or ""
            )
            if not title:
                continue

            # 提取正文/摘要
            body = (
                raw.get("content")
                or raw.get("summary")
                or raw.get("digest")
                or title
            )

            # 提取 URL
            url = (
                raw.get("url")
                or raw.get("link")
                or raw.get("news_url")
                or ""
            )

            # 提取发布时间
            pub_time = (
                raw.get("publish_time")
                or raw.get("published")
                or raw.get("datetime")
                or now_iso
            )

            items.append(NewsItem(
                title=str(title),
                url=str(url),
                published_at=str(pub_time),
                source=source_type,
                summary=str(body),
                status="ok",
            ))

        return items

    # ── 缓存与兜底 ───────────────────────────────────────────────────

    def _save_cache(self, items: list) -> None:
        """将成功采集的新闻保存到本地 JSON 缓存."""
        try:
            NEWS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = [it.to_dict() for it in items]
            _json.dump(data, NEWS_CACHE_PATH.open("w"), ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存新闻缓存失败: %s", e)

    @staticmethod
    def _load_cache() -> Optional[list[dict]]:
        """加载本地缓存的新闻数据."""
        if not NEWS_CACHE_PATH.exists():
            return None
        try:
            data = _json.loads(NEWS_CACHE_PATH.read_text())
            if data and isinstance(data, list) and len(data) > 0:
                return data
        except Exception as e:
            logger.warning("加载新闻缓存失败: %s", e)
        return None

    @staticmethod
    def _builtin_fallback() -> list:
        """内置测试新闻 — 极端兜底，确保系统永不因为缺新闻而停摆."""
        from connectors.base import NewsItem
        now = datetime.now(timezone.utc).isoformat()
        return [
            NewsItem(
                title="BTC 维持高位震荡，市场关注美联储利率决议",
                url="",
                published_at=now,
                source="fallback",
                summary="比特币价格在65000-68000美元区间震荡，投资者等待本周美联储利率决议。分析师认为，若维持利率不变可能推动风险资产上涨。",
                status="fallback",
            ),
            NewsItem(
                title="以太坊 Layer2 总锁仓量突破 500 亿美元",
                url="",
                published_at=now,
                source="fallback",
                summary="以太坊Layer2网络总锁仓量(TVL)创历史新高，达到500亿美元。Arbitrum和Optimism领跑，Base链增长迅速。",
                status="fallback",
            ),
            NewsItem(
                title="SEC 推迟以太坊现货 ETF 期权交易决定",
                url="",
                published_at=now,
                source="fallback",
                summary="美国证券交易委员会(SEC)推迟了对以太坊现货ETF期权交易的决定，新截止日期为下月。市场对此已有预期，ETH价格反应平淡。",
                status="fallback",
            ),
            NewsItem(
                title="美国CPI数据符合预期，风险资产小幅上涨",
                url="",
                published_at=now,
                source="fallback",
                summary="最新公布的通胀数据符合市场预期，强化了市场对美联储降息的预期。美股、加密市场均出现温和上涨。",
                status="fallback",
            ),
            NewsItem(
                title="币安宣布上线新的质押产品，支持多链资产",
                url="",
                published_at=now,
                source="fallback",
                summary="全球最大加密货币交易所币安宣布推出新的质押产品，支持包括SOL、AVAX、DOT等多个公链资产，年化收益率4-12%。",
                status="fallback",
            ),
        ]

def collect_news() -> list[dict]:
    """便捷函数: 采集新闻并返回统一字典列表."""
    collector = MultiSourceNewsCollector()
    result = collector.fetch_all()
    if result == "missing":
        return []
    return result  # type: ignore
