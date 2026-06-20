"""Backtest runner — loads market_snapshot.json data and runs SafeBacktestEngine.

Usage:
    python3 -m backtest.runner                           # default: BTCUSDT 1h
    python3 -m backtest.runner --symbol ETHUSDT --interval 1h
    python3 -m backtest.runner --symbol BTCUSDT --interval 15m --fee 0.001 --slippage 0.0005
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from backtest.engine import SafeBacktestEngine
from backtest.strategies import ma5_20_crossover

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("backtest.runner")

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "market_snapshot.json"


def load_klines(symbol: str, source_filter: str = "binance") -> list[dict]:
    """Load Klines for a symbol from the snapshot, deduplicating by timestamp."""
    if not SNAPSHOT_PATH.exists():
        print(f"❌ 找不到数据文件: {SNAPSHOT_PATH}")
        print("   请先运行数据采集: python3 -c 'from data_layer.unified_ingestor import DataIngestor; DataIngestor().ingest()'")
        sys.exit(1)

    with open(SNAPSHOT_PATH) as f:
        snapshot = json.load(f)

    raw = [
        k for k in snapshot.get("klines", [])
        if k.get("symbol") == symbol and k.get("source") == source_filter
    ]

    # Deduplicate by timestamp (keep first occurrence)
    seen = set()
    deduped = []
    for k in raw:
        ts = k["timestamp"]
        if ts not in seen:
            seen.add(ts)
            deduped.append(k)

    # Sort chronologically
    deduped.sort(key=lambda k: k["timestamp"])
    logger.info("Loaded %d %s klines for %s", len(deduped), source_filter, symbol)
    return deduped


def run(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    source: str = "binance",
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage: float = 0.0,
) -> dict:
    """Run backtest and print results."""
    klines = load_klines(symbol, source)
    if not klines:
        print(f"❌ 没有找到 {symbol} 的 {source} K线数据")
        return {}

    engine = SafeBacktestEngine(
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage=slippage,
    )

    result = engine.run(klines, ma5_20_crossover, symbol=symbol, interval=interval)

    print("\n" + result.summary_text)

    # Print trade table
    if result.trades:
        print(f"\n─── 交易明细 ({len(result.trades)} 笔) ───")
        print(f"{'#':>4} {'入场时间':>22} {'入场价':>10} {'出场时间':>22} {'出场价':>10} {'盈亏':>10} {'原因'}")
        print("-" * 110)
        for idx, t in enumerate(result.trades, 1):
            print(
                f"{idx:>4} {t['entry_time']:>22} {t['entry_price']:>10.2f} "
                f"{t['exit_time']:>22} {t['exit_price']:>10.2f} "
                f"{t['pnl']:>+10.2f} {t['reason']}"
            )

    # JSON output path
    output_dir = Path(__file__).resolve().parent.parent / "data" / "backtest"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{symbol}_{interval}_backtest.json"
    output_path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    print(f"\n📁 完整结果已保存: {output_path}")

    return result.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="量化策略回测 — MA5/20 金叉死叉")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对 (默认 BTCUSDT)")
    parser.add_argument("--interval", default="1h", help="K线周期 (默认 1h)")
    parser.add_argument("--source", default="binance", help="数据源 (默认 binance)")
    parser.add_argument("--capital", type=float, default=10_000.0, help="初始资金 USDT")
    parser.add_argument("--fee", type=float, default=0.001, help="费率 (默认 0.001 = 0.1%%)")
    parser.add_argument("--slippage", type=float, default=0.0, help="滑点 (默认 0)")
    args = parser.parse_args()

    run(
        symbol=args.symbol,
        interval=args.interval,
        source=args.source,
        initial_capital=args.capital,
        fee_rate=args.fee,
        slippage=args.slippage,
    )


if __name__ == "__main__":
    main()
