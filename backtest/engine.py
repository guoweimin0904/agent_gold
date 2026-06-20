"""Safe backtesting engine — event-driven, per-trade recording, fee & slippage support.

No look-ahead: signals use only data available up to the current candle.
Every trade records entry/exit timestamps, prices, PnL, and reason.
"""

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable

logger = logging.getLogger("backtest.engine")


@dataclass
class TradeRecord:
    """A single completed round-trip trade (entry → exit)."""
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    side: str                          # "long"
    quantity: float
    pnl: float                         # after fees & slippage
    pnl_pct: float                     # percentage return of this trade
    fee_total: float                   # total fees paid (entry + exit)
    reason: str                        # why this trade was taken / closed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    """Complete backtest result with all metrics."""
    symbol: str
    interval: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    trade_count: int
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    fee_rate: float = 0.001
    slippage: float = 0.0
    sample_sufficient: bool = True      # True if trade_count >= 30
    disclaimer: str = (
        "⚠️ 本回测结果仅供研究参考，不构成任何投资建议。"
        "过去的表现不代表未来的收益。实际交易可能存在滑点、流动性、"
        "交易延迟等不可预见的风险。"
    )

    @property
    def summary_text(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"─── 回测报告: {self.symbol} ({self.interval}) ───",
            f"初始资金: {self.initial_capital:,.2f} USDT",
            f"最终权益: {self.final_equity:,.2f} USDT",
            f"总收益率: {self.total_return_pct:+.2f}%",
            f"最大回撤: {self.max_drawdown_pct:.2f}%",
            f"胜率: {self.win_rate:.2%}",
            f"盈亏比: {self.profit_factor:.2f}",
            f"交易次数: {self.trade_count}",
            f"费率: {self.fee_rate:.3%} / 滑点: {self.slippage:.3%}",
        ]
        if not self.sample_sufficient:
            lines.append("⚠️  样本不足: 交易次数 < 30，结论仅供参考，置信度低。")
        lines.append("")
        lines.append(self.disclaimer)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "initial_capital": self.initial_capital,
            "final_equity": round(self.final_equity, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "trade_count": self.trade_count,
            "fee_rate": self.fee_rate,
            "slippage": self.slippage,
            "sample_sufficient": self.sample_sufficient,
            "sample_warning": None if self.sample_sufficient else "交易次数 < 30，结论仅供参考",
            "disclaimer": self.disclaimer,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
        }


class SafeBacktestEngine:
    """Event-driven backtest engine with full trade recording.

    Arguments:
        initial_capital: Starting portfolio value in USDT.
        fee_rate: Trading fee as a fraction (e.g. 0.001 = 0.1%).
        slippage: Additional price slippage as fraction (e.g. 0.0005 = 0.05%).
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage: float = 0.0,
    ) -> None:
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.slippage = slippage

    def run(
        self,
        ohlcv: list[dict[str, Any]],
        signal_fn: Callable[[list[dict[str, Any]], int], str],
        symbol: str = "UNKNOWN",
        interval: str = "1h",
    ) -> BacktestResult:
        """
        Run a backtest.

        Parameters
        ----------
        ohlcv : list[dict]
            Each dict must have: timestamp, open, high, low, close, volume.
            Sorted chronologically (oldest first).
        signal_fn : Callable
            ``signal_fn(data, i) -> "buy" | "sell" | "hold"``
            Called for each candle i (0-indexed). Receives the full data list
            and current index. Must only use data[:i+1] — no future data.
        symbol, interval : str
            Metadata for the result.

        Returns
        -------
        BacktestResult
        """
        if not ohlcv:
            raise ValueError("Empty OHLCV data")

        logger.info("Running backtest on %s (%s) — %d candles", symbol, interval, len(ohlcv))

        trades: list[TradeRecord] = []
        equity_curve: list[dict[str, Any]] = []

        cash = self.initial_capital
        position = 0.0  # units held
        entry_price = 0.0
        entry_time = ""

        for i in range(len(ohlcv)):
            candle = ohlcv[i]
            ts = candle["timestamp"]
            close = float(candle["close"])

            # ── Generate signal (NO future data) ──────────────────
            signal = signal_fn(ohlcv, i)

            # ── Execute exit first (if we have a position) ────────
            if position > 0 and signal == "sell":
                # Apply slippage on exit: sell at slightly lower price
                exit_price = close * (1 - self.slippage)
                fee = exit_price * position * self.fee_rate
                proceeds = exit_price * position - fee
                pnl = proceeds - (entry_price * position)
                pnl_pct = (exit_price - entry_price) / entry_price - self.fee_rate * 2 - self.slippage

                trades.append(TradeRecord(
                    entry_time=entry_time,
                    entry_price=round(entry_price, 2),
                    exit_time=ts,
                    exit_price=round(exit_price, 2),
                    side="long",
                    quantity=round(position, 6),
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 4),
                    fee_total=round(self.fee_rate * entry_price * position + fee, 2),
                    reason=f"MA5死叉MA20卖出 @ {exit_price:.2f}",
                ))
                cash += proceeds
                position = 0.0

            # ── Execute entry ─────────────────────────────────────
            if position == 0 and signal == "buy":
                # Apply slippage on entry: buy at slightly higher price
                buy_price = close * (1 + self.slippage)
                fee = buy_price * self.fee_rate
                cost_per_unit = buy_price * (1 + self.fee_rate)
                max_units = cash * 0.95 / cost_per_unit  # keep 5% cash buffer

                if max_units > 0:
                    position = max_units
                    entry_price = buy_price
                    entry_time = ts
                    cash -= buy_price * position * (1 + self.fee_rate)

            # ── Record equity snapshot ────────────────────────────
            equity = cash + position * close
            equity_curve.append({
                "timestamp": ts,
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "position_value": round(position * close, 2),
                "in_position": position > 0,
            })

        # ── Force close any remaining position at last close ───────
        if position > 0 and ohlcv:
            last = ohlcv[-1]
            final_price = float(last["close"]) * (1 - self.slippage)
            fee = final_price * position * self.fee_rate
            proceeds = final_price * position - fee
            pnl = proceeds - (entry_price * position)
            trades.append(TradeRecord(
                entry_time=entry_time,
                entry_price=round(entry_price, 2),
                exit_time=last["timestamp"],
                exit_price=round(final_price, 2),
                side="long",
                quantity=round(position, 6),
                pnl=round(pnl, 2),
                pnl_pct=round((final_price - entry_price) / entry_price, 4),
                fee_total=round(self.fee_rate * entry_price * position + fee, 2),
                reason="回测结束强制平仓",
            ))
            cash += proceeds
            position = 0.0

        # ── Compute aggregated metrics ────────────────────────────
        final_equity = cash  # all in cash now
        total_return = (final_equity / self.initial_capital - 1) * 100

        # Max drawdown from equity curve
        peak = float("-inf")
        max_dd = 0.0
        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        # Win rate & profit factor
        trade_count = len(trades)
        sample_sufficient = trade_count >= 30
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl <= 0]
        win_rate = len(winning_trades) / trade_count if trade_count > 0 else 0.0

        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        return BacktestResult(
            symbol=symbol,
            interval=interval,
            initial_capital=self.initial_capital,
            final_equity=round(final_equity, 2),
            total_return_pct=round(total_return, 2),
            max_drawdown_pct=round(max_dd, 2),
            win_rate=win_rate,
            profit_factor=profit_factor,
            trade_count=trade_count,
            trades=[t.to_dict() for t in trades],
            equity_curve=equity_curve,
            fee_rate=self.fee_rate,
            slippage=self.slippage,
            sample_sufficient=sample_sufficient,
        )
