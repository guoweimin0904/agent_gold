"""Decision schema — the exact, fixed output format for ComprehensiveDecisionAgent.

Every field is mandatory. No "必涨", "梭哈", "稳赚" allowed.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal

MarketState = Literal["trend", "range", "panic", "fomo"]
Direction = Literal["long", "short", "wait"]


@dataclass
class ComprehensiveDecision:
    """
    Structured decision from ComprehensiveDecisionAgent.

    All fields are explained for beginner understanding.
    """

    symbol: str = ""

    # ── Market context ──
    market_state: MarketState = "range"
    """当前市场状态: trend=趋势, range=震荡, panic=恐慌, fomo=FOMO追涨"""

    direction: Direction = "wait"
    """建议方向: long=做多, short=做空, wait=等待"""

    # ── Scores ──
    final_score: float = 0.0
    """综合评分 0-100"""

    confidence: float = 0.0
    """信心指数 0.0-1.0"""

    # ── Entry / Exit rules ──
    entry_condition: str = ""
    """
    不是立刻买，而是满足什么条件才允许进入。
    例如: "BTC 突破 68000 且 RSI < 65"
    """

    invalid_condition: str = ""
    """
    什么情况说明原逻辑失效，必须撤销计划。
    例如: "价格跌破 65000" 或 "新闻事件被证伪"
    """

    stop_loss: str = ""
    """止损条件，例如 "65000" 或 "-5% ATR" 或 "EMA21 破位" """

    take_profit: str = ""
    """止盈条件，例如 "72000" 或 "+10%" 或 "RSI>70 减仓" """

    # ── Position ──
    position_suggestion: str = ""
    """
    仓位建议，不是收益承诺。新系统默认低仓位。
    例如: "5% 初始仓位，确认趋势后加至 10%"
    """

    # ── Reasoning ──
    reason_summary: list[str] = field(default_factory=list)
    """决策理由列表，每条一句话"""

    conflict_signals: list[str] = field(default_factory=list)
    """
    相互矛盾的信号必须写出来。
    例如: "新闻利好（BTC ETF 获批）但资金流出（交易所净流出）"
    """

    # ── Safety ──
    need_human_confirm: bool = True
    """
    默认 true，新手阶段所有交易都需要人工确认。
    仅当 final_score < 30（自动 avoid）时可为 False。
    """

    # ── Metadata ──
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    vetoed: bool = False
    veto_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "market_state": self.market_state,
            "direction": self.direction,
            "final_score": round(self.final_score, 1),
            "confidence": round(self.confidence, 2),
            "entry_condition": self.entry_condition,
            "invalid_condition": self.invalid_condition,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_suggestion": self.position_suggestion,
            "reason_summary": self.reason_summary,
            "conflict_signals": self.conflict_signals,
            "need_human_confirm": self.need_human_confirm,
            "generated_at": self.generated_at,
            "vetoed": self.vetoed,
            "veto_reason": self.veto_reason,
            "disclaimer": self.disclaimer(),
        }

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def disclaimer() -> str:
        return (
            "⚠️ 本决策仅供研究参考，不构成任何投资建议。"
            "禁止将本输出解读为\"必涨\"\"梭哈\"\"稳赚\"。"
            "所有交易决策存在亏损风险，请自行承担。"
        )


# ── Helper: determine direction from final_score + veto ─────────────

def resolve_direction(
    final_score: float,
    market_state: MarketState,
    vetoed: bool = False,
    backtest_win_rate: float = 0.0,
    news_direction: str = "neutral",
    scoring_decision: str = "avoid",
    long_cycle_bias: str = "neutral",  # "bullish" | "bearish" | "neutral"
) -> Direction:
    """
    Resolve final direction from multi-modal inputs.

    决策矩阵 (优化后):
      - vetoed / avoid / score<45 → wait
      - score 80+ trend/fomo → long
      - score 65-79 trend → long; panic → short
      - score 50-64 → 技术+资金+长周期确认后 long
      - 长周期牛市中放宽做多条件
    """
    if vetoed:
        return "wait"

    if scoring_decision == "avoid":
        if final_score >= 55:
            return "wait"
        return "wait"

    # 低于 45 分：直接 wait
    if final_score < 45:
        return "wait"

    # 80+ 强信号
    if final_score >= 80:
        if market_state in ("trend", "fomo"):
            return "long"
        if market_state == "range" and news_direction == "bullish":
            return "long"
        return "wait"

    # 65-79: 趋势/震荡中有信号则做多，恐慌中做空
    if final_score >= 65:
        if market_state == "panic":
            return "short"
        if market_state in ("trend", "fomo"):
            return "long"
        if market_state == "range" and news_direction == "bullish":
            return "long"
        if market_state == "range" and backtest_win_rate >= 0.45:
            return "long"
        return "wait"

    # 50-64: 需要技术+资金确认
    if final_score >= 50:
        if market_state == "panic":
            return "wait"
        if long_cycle_bias == "bullish" and market_state in ("trend", "range"):
            if backtest_win_rate >= 0.4:
                return "long"
        if market_state == "trend" and news_direction == "bullish" and backtest_win_rate >= 0.45:
            return "long"
        return "wait"

    # 45-49: 仅长牛+趋势+高胜率才做
    if long_cycle_bias == "bullish" and market_state == "trend" and backtest_win_rate >= 0.5:
        return "long"
    return "wait"
