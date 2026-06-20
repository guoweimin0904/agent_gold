"""Data Layer — unified read-only data ingestion for AI Quant Agent.

Provides market_snapshot() which collects Klines, market overview, and news
from all configured sources and outputs a single market_snapshot.json.
"""
