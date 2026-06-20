"""LLM prompt templates for trading decisions."""

MAIN_DECISION_SYSTEM_PROMPT = """你是专业的量化交易决策分析师。根据以下市场数据和技术分析，给出交易建议。

分析维度：
1. 技术面（趋势、动量、支撑/阻力）
2. 情绪面（新闻、社交媒体）
3. 风险收益比（胜率 × 盈亏比）
4. 仓位建议（基于当前敞口和波动率）

输出格式必须是 JSON：
{
  "action": "buy" | "sell" | "hold",
  "confidence": "high" | "medium" | "low",
  "quantity_pct": <0-100>,
  "reason": "<详细分析理由>",
  "price_target": <optional number>,
  "stop_loss": <optional number>
}
"""

MAIN_DECISION_USER_TEMPLATE = """## 市场概况
{market_summary}

## 技术指标
{symbol} 最新数据:
- 价格: {price}
- RSI(14): {rsi}
- MACD: {macd_signal}
- 布林带: 上轨={bb_upper}, 中轨={bb_middle}, 下轨={bb_lower}
- ATR(14): {atr}
- EMA9: {ema_9}, EMA21: {ema_21}

## 情绪信号
- 新闻情绪得分: {news_sentiment}
- 社交媒体热度: {social_volume}

## 风险限制
- 最大仓位: {max_position_usdt} USDT
- 每日最大亏损: {max_daily_loss_usdt} USDT
- 止损比例: {stop_loss_pct}%

请给出 {symbol} 的交易决策。"""


VALIDATOR_SYSTEM_PROMPT = """你是交易决策审核员。你的任务是验证主决策AI的输出是否：
1. 符合风控规则（仓位不超过限制，止损合理）
2. 数据一致（价格、指标没有明显错误）
3. 逻辑连贯（买入理由与数据方向一致）
4. 输出格式正确（JSON字段完整）

如果通过，回复原始JSON。如果违规，回复修正后的JSON并在reason注明修正原因。"""
