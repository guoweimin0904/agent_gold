"""Daily report generator — summary of trades, PnL, risk metrics."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from config import BASE_DIR

logger = logging.getLogger(__name__)

REPORT_DIR = BASE_DIR / "reports"


class DailyReport:
    """Generate daily performance summaries."""

    def __init__(self) -> None:
        self._today = date.today()

    def generate(
        self,
        paper_balance: float,
        open_positions: dict[str, Any],
        decisions_today: list[dict[str, Any]],
        risk_metrics: dict[str, Any] | None = None,
    ) -> str:
        """Generate a markdown daily report."""
        lines = [
            f"# 量化交易日报 — {self._today.isoformat()}",
            "",
            "## 账户概览",
            f"- 当前余额: `${paper_balance:.2f}`",
            f"- 持仓数: `{len(open_positions)}`",
            "",
            "## 今日交易",
        ]

        if decisions_today:
            for d in decisions_today:
                lines.append(f"- {d.get('time', '?')} | {d.get('symbol', '?')} | "
                             f"**{d.get('action', '?').upper()}** | "
                             f"原因: {d.get('reason', 'N/A')}")
        else:
            lines.append("- 今日无交易")

        lines.append("")
        lines.append("## 风控状态")
        if risk_metrics:
            for k, v in risk_metrics.items():
                lines.append(f"- {k}: {v}")
        else:
            lines.append("- 正常")

        return "\n".join(lines)

    def save(self, content: str, filename: str | None = None) -> Path:
        """Save report to disk."""
        filename = filename or f"daily_{self._today.isoformat()}.md"
        path = REPORT_DIR / filename
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        logger.info("Report saved: %s", path)
        return path
