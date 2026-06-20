"""Standalone performance metrics — total_return, max_drawdown, win_rate, profit_factor.

All functions operate on TradeRecord dicts. No look-ahead, no future data.
"""
from __future__ import annotations

from typing import Any


def compute_total_return(initial: float, final: float) -> float:
    """Total return as percentage."""
    if initial <= 0:
        return 0.0
    return (final / initial - 1) * 100


def compute_max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
    """Maximum peak-to-trough drawdown in percentage."""
    if not equity_curve:
        return 0.0
    peak = float("-inf")
    max_dd = 0.0
    for point in equity_curve:
        eq = point.get("equity", 0)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def compute_win_rate(trades: list[dict[str, Any]]) -> float:
    """Fraction of trades with positive PnL."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades)


def compute_profit_factor(trades: list[dict[str, Any]]) -> float:
    """Gross profit / gross loss. Returns float('inf') if no losing trades."""
    if not trades:
        return 0.0
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) <= 0))
    if gross_loss == 0:
        return float("inf")
    return gross_profit / gross_loss


def sample_warning(trade_count: int) -> str | None:
    """Return warning if sample is insufficient (< 30 trades)."""
    if trade_count < 30:
        return "样本不足: 交易次数 < 30，结论仅供参考，置信度低"
    return None


def disclaimer_text() -> str:
    return (
        "⚠️ 本回测结果仅供研究参考，不构成任何投资建议。"
        "过去的表现不代表未来的收益。实际交易可能存在滑点、流动性、"
        "交易延迟等不可预见的风险。"
    )
