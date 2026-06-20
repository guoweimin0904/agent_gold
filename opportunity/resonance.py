"""Resonance detector — policy + fund flow resonance = strongest candidate.

When policy_score is high (≥70) AND fund_flow_score confirms (≥65),
the signal_strength is maximum and the candidate is flagged.
"""

import logging
from typing import Any

from opportunity.schemas import ResonanceSignal

logger = logging.getLogger("opportunity.resonance")


class ResonanceDetector:
    """
    Detect policy + fund flow resonance.

    政策+资金共振 = 强候选筛选器
    - policy_score ≥ 70 + fund_flow ≥ 65 → candidate=True
    - signal_strength = min(policy/100, fund/100) * 0.7 + agreement * 0.3
    """

    def detect(
        self,
        symbol: str,
        policy_signal: dict[str, Any] | None = None,
        fund_flow_signal: dict[str, Any] | None = None,
    ) -> ResonanceSignal:
        """Detect resonance between policy and fund flow signals."""
        if not policy_signal or not fund_flow_signal:
            return ResonanceSignal(
                symbol=symbol, final_score=0, signal_strength=0,
                candidate=False, summary="数据不足，无法检测共振",
            )

        ps = policy_signal.get("policy_score", 0)
        fs = fund_flow_signal.get("fund_flow_score", 0)
        benefit_sector = policy_signal.get("benefit_sector", "")

        # Compute resonance
        agreement = 1 - abs(ps - fs) / 100  # 1.0 if identical, 0 if opposite
        strength = min(ps / 100, fs / 100) * 0.6 + agreement * 0.4
        final_score = (ps + fs) / 2
        candidate = ps >= 70 and fs >= 65

        if candidate:
            summary = (
                f"🔴 政策+资金共振: policy_score={ps:.0f} + fund_flow={fs:.0f} "
                f"→ 信号强度{strength:.0%} | 受益板块: {benefit_sector}"
            )
        elif ps >= 60 and fs >= 50:
            summary = (
                f"🟡 部分共振: policy={ps:.0f} fund={fs:.0f} "
                f"→ 观察中，等资金确认"
            )
        else:
            summary = (
                f"⚪ 未共振: policy={ps:.0f} fund={fs:.0f} "
                f"→ 等待政策或资金信号"
            )

        return ResonanceSignal(
            symbol=symbol,
            policy_score=ps,
            fund_flow_score=fs,
            final_score=round(final_score, 1),
            signal_strength=round(strength, 2),
            candidate=candidate,
            benefit_sector=benefit_sector,
            summary=summary,
        )
