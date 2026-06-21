"""Data connectors — Binance, CoinGecko, News, X/Twitter, and A-Share (AKShare)."""

from connectors.ashare import (
    get_spot as ashare_get_spot,
    get_klines as ashare_get_klines,
    get_fundamentals as ashare_get_fundamentals,
    get_fund_flow as ashare_get_fund_flow,
)
from connectors.ashare_news import (
    get_stock_news as ashare_get_news,
    get_corporate_events as ashare_get_corporate_events,
    get_market_sentiment as ashare_sentiment,
)
