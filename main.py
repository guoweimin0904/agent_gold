"""AI Quant Agent — Main entry point."""

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

from analysis.decision_schema import TradingDecision
from analysis.event_scoring import EventScorer
from analysis.indicators import add_all_indicators
from backtest.engine import BacktestEngine
from connectors.binance_rest import BinanceRest
from connectors.coingecko import CoinGecko
from execution.kill_switch import KillSwitch
from execution.paper_trade import PaperTrade
from llm.main_decision_agent import MainDecisionAgent
from llm.validator_agent import ValidatorAgent
from risk.risk_control import RiskController
from reports.daily_report import DailyReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "agent.log"),
    ],
)
logger = logging.getLogger("quant_agent")


class QuantAgent:
    """Orchestrator for the AI quant trading system."""

    def __init__(self) -> None:
        self.binance = BinanceRest()
        self.coingecko = CoinGecko()
        self.decision_agent = MainDecisionAgent()
        self.validator = ValidatorAgent()
        self.paper_trade = PaperTrade()
        self.kill_switch = KillSwitch()
        self.risk_controller = RiskController()
        self.scorer = EventScorer()
        self.reporter = DailyReport()

    def run_once(self, symbol: str = "BTCUSDT") -> None:
        """Single decision cycle."""
        logger.info("Starting decision cycle for %s", symbol)

        # 1. Check kill switch
        if not self.kill_switch.check_before_trade():
            logger.warning("Kill switch active — skipping")
            return

        # 2. Fetch market data
        try:
            klines = self.binance.get_klines(symbol, interval="1h", limit=100)
            # Convert to DataFrame with indicators (simplified)
            price = self.binance.get_ticker_price(symbol)
        except Exception as e:
            logger.error("Data fetch failed: %s", e)
            return

        # 3. Get LLM decision
        try:
            market_data = {
                "summary": f"{symbol} price: {price}",
                "price": str(price),
                "rsi": "50",  # placeholder — compute from klines
                "macd_signal": "neutral",
                # ... real indicators from analysis/indicators.py
            }
            decision = self.decision_agent.decide(symbol, market_data)
            logger.info("Decision: %s → %s", symbol, decision.action)
        except Exception as e:
            logger.error("Decision agent failed: %s", e)
            return

        # 4. Validate
        try:
            validated = self.validator.validate(decision)
        except Exception as e:
            logger.error("Validator failed: %s", e)
            validated = decision

        # 5. Risk check
        approved, reason = self.risk_controller.check_order(
            symbol, validated.action, validated.quantity_pct, {}
        )
        if not approved:
            logger.warning("Risk check denied: %s", reason)
            return

        # 6. Execute (paper trade)
        result = self.paper_trade.execute(validated, price)
        logger.info("Execution result: %s", result.get("status"))
        logger.info("Balance: %.2f | Equity: %.2f",
                    self.paper_trade.balance, self.paper_trade.total_equity)

    def run_backtest(self, symbol: str, interval: str = "1h", days: int = 365) -> None:
        """Fetch historical data and run a simple backtest."""
        logger.info("Running backtest for %s (%s, %d days)", symbol, interval, days)
        engine = BacktestEngine()
        # TODO: fetch klines → DataFrame → define signal function → engine.run()
        logger.info("Backtest completed")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Quant Agent")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    parser.add_argument("--backtest", action="store_true", help="Run backtest mode")
    parser.add_argument("--once", action="store_true", help="Single decision cycle")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon (loop)")
    args = parser.parse_args()

    agent = QuantAgent()

    if args.backtest:
        agent.run_backtest(args.symbol)
    elif args.once:
        agent.run_once(args.symbol)
    elif args.daemon:
        import time
        from config import SchedulerConfig
        interval = SchedulerConfig().check_interval_minutes
        logger.info("Starting daemon mode (every %d min)", interval)
        while True:
            agent.run_once(args.symbol)
            time.sleep(interval * 60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
