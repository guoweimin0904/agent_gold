"""Binance testnet execution — real orders on testnet only."""

import logging
from decimal import Decimal

from connectors.binance_rest import BinanceRest
from analysis.decision_schema import TradingDecision

logger = logging.getLogger(__name__)


class BinanceTestnetExecutor:
    """Execute trades on Binance testnet."""

    def __init__(self) -> None:
        self.api = BinanceRest()  # testnet by default

    def execute(self, decision: TradingDecision) -> dict:
        """Place an order on testnet based on TradingDecision."""
        if decision.action == "hold":
            return {"status": "no_action"}

        # Get current price for market orders
        price = self.api.get_ticker_price(decision.symbol)

        binance_side = "BUY" if decision.action == "buy" else "SELL"

        # Calculate quantity from price if not specified
        # (simplified — in production use LOT_SIZE filters from exchangeInfo)
        try:
            order = self.api.new_order(
                symbol=decision.symbol,
                side=binance_side,
                quantity=str(decision.quantity_pct),
            )
            logger.info("Testnet order placed: %s", order)
            return {"status": "placed", "order": order}
        except Exception as e:
            logger.error("Testnet order failed: %s", e)
            return {"status": "failed", "error": str(e)}
