"""Configuration loader — reads from .env with sensible defaults."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class BinanceConfig:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    testnet = True


class CoinGeckoConfig:
    api_key = os.getenv("COINGECKO_API_KEY", "")


class NewsAPIConfig:
    api_key = os.getenv("NEWS_API_KEY", "")


class DataLayerConfig:
    request_timeout = int(os.getenv("DATA_REQUEST_TIMEOUT", "30"))
    retry_max = int(os.getenv("DATA_RETRY_MAX", "3"))
    retry_delay = int(os.getenv("DATA_RETRY_DELAY", "2"))


class ExecutionConfig:
    """Execution gate configuration.

    ENABLE_REAL_TRADING:      Must be explicitly set to 'true' for real trades.
    EXECUTION_MODE:           'paper' | 'testnet' | 'real'
    EXCHANGE_API_WITHDRAWAL:  Whether the API key has withdrawal permission.
    EXCHANGE_IP_WHITELIST:    Comma-separated IPs or 'enabled' / 'disabled'.
    STOP_LOSS_REQUIRED:       Whether stop-loss is mandatory (default true).
    INVALID_COND_REQUIRED:    Whether invalid_condition is mandatory (default true).
    POSITION_LIMIT_PCT:       Max position per symbol as % of capital.
    """
    enable_real_trading = os.getenv("ENABLE_REAL_TRADING", "false").strip().lower() == "true"
    execution_mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
    exchange_api_withdrawal = os.getenv("EXCHANGE_API_WITHDRAWAL", "false").strip().lower() == "true"
    exchange_ip_whitelist = os.getenv("EXCHANGE_IP_WHITELIST", "").strip()
    stop_loss_required = os.getenv("STOP_LOSS_REQUIRED", "true").strip().lower() == "true"
    invalid_cond_required = os.getenv("INVALID_COND_REQUIRED", "true").strip().lower() == "true"
    position_limit_pct = float(os.getenv("POSITION_LIMIT_PCT", "20"))

    @property
    def ip_whitelist_enabled(self) -> bool:
        return bool(self.exchange_ip_whitelist) and self.exchange_ip_whitelist.lower() not in ("", "disabled", "false")

    @property
    def mode_display(self) -> str:
        return {"paper": "模拟交易", "testnet": "测试网", "real": "实盘"}.get(self.execution_mode, "unknown")


class LLMConfig:
    provider = os.getenv("LLM_PROVIDER", "openai")
    api_key = os.getenv("LLM_API_KEY", "")
    model = os.getenv("LLM_MODEL", "gpt-4o")
    base_url = os.getenv("LLM_BASE_URL", "")


class RiskConfig:
    max_position_size_usdt = float(os.getenv("MAX_POSITION_SIZE_USDT", "1000"))
    max_daily_loss_usdt = float(os.getenv("MAX_DAILY_LOSS_USDT", "200"))
    stop_loss_pct = float(os.getenv("STOP_LOSS_PCT", "0.05"))


class SchedulerConfig:
    check_interval_minutes = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))


class NotificationConfig:
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
