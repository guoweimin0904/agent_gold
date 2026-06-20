"""Main LLM trading decision agent — aggregates data and makes calls."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

import config
from analysis.decision_schema import TradingDecision
from llm.prompts import (
    MAIN_DECISION_SYSTEM_PROMPT,
    MAIN_DECISION_USER_TEMPLATE,
)


class MainDecisionAgent:
    """Primary decision-making agent powered by an LLM."""

    def __init__(self) -> None:
        llm_cfg = config.LLMConfig()
        self.client = OpenAI(
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url or None,
        )
        self.model = llm_cfg.model

    def decide(
        self,
        symbol: str,
        market_data: dict[str, Any],
        sentiment_data: dict[str, Any] | None = None,
    ) -> TradingDecision:
        """Generate a trading decision based on market & sentiment data."""
        user_msg = MAIN_DECISION_USER_TEMPLATE.format(
            market_summary=market_data.get("summary", "N/A"),
            symbol=symbol,
            price=market_data.get("price", "N/A"),
            rsi=market_data.get("rsi", "N/A"),
            macd_signal=market_data.get("macd_signal", "N/A"),
            bb_upper=market_data.get("bb_upper", "N/A"),
            bb_middle=market_data.get("bb_middle", "N/A"),
            bb_lower=market_data.get("bb_lower", "N/A"),
            atr=market_data.get("atr", "N/A"),
            ema_9=market_data.get("ema_9", "N/A"),
            ema_21=market_data.get("ema_21", "N/A"),
            news_sentiment=(sentiment_data or {}).get("news", "N/A"),
            social_volume=(sentiment_data or {}).get("social_volume", "N/A"),
            max_position_usdt=config.RiskConfig().max_position_size_usdt,
            max_daily_loss_usdt=config.RiskConfig().max_daily_loss_usdt,
            stop_loss_pct=config.RiskConfig().stop_loss_pct,
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MAIN_DECISION_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        assert raw is not None
        parsed = json.loads(raw)

        decision = TradingDecision(
            symbol=symbol,
            action=parsed.get("action", "hold"),
            confidence=parsed.get("confidence", "low"),
            quantity_pct=float(parsed.get("quantity_pct", 0)),
            reason=parsed.get("reason", ""),
        )

        if errors := decision.validate():
            raise ValueError(f"Invalid decision: {errors}")

        return decision
