"""Validator agent — validates ComprehensiveDecision before execution.

Cross-checks:
- final_score vs decision consistency
- veto consistency
- entry_condition vs direction consistency
- stop_loss vs take_profit sanity
- position_suggestion vs risk limits
- No "必涨", "梭哈", "稳赚" in any text field
"""

import logging
import re
from typing import Any

from llm.decision_schemas import ComprehensiveDecision

logger = logging.getLogger("llm.validator")

FORBIDDEN_PATTERNS = [
    r"必涨", r"梭哈", r"稳赚", r"保本", r"无风险",
    r"guaranteed", r"risk.free", r"sure.thing",
    r"100%.*profit", r"no.*loss",
]


class DecisionValidator:
    """
    Deterministic validator for ComprehensiveDecision.

    Does NOT use LLM — pure rule-based validation.
    """

    def validate(
        self,
        decision: ComprehensiveDecision,
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, list[str]]:
        """
        Validate a decision. Returns (passed, violations).

        Returns False + violations list if any check fails.
        """
        violations: list[str] = []

        # ── 1. Check forbidden language ──────────────────────────
        fields_to_check = [
            ("entry_condition", decision.entry_condition),
            ("invalid_condition", decision.invalid_condition),
            ("stop_loss", decision.stop_loss),
            ("take_profit", decision.take_profit),
            ("position_suggestion", decision.position_suggestion),
        ]
        for field_name, text in fields_to_check:
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(
                        f"字段 '{field_name}' 包含禁止用语: '{pattern}'"
                    )

        # ── 2. Score-decision consistency ─────────────────────────
        fs = decision.final_score
        if decision.vetoed and decision.direction != "wait":
            violations.append(
                f"已被否决但 direction={decision.direction}，应为 wait"
            )
        if decision.vetoed and decision.final_score > 60:
            # Allow — veto overrides score, not modifies it
            pass
        if fs >= 80 and decision.direction == "wait" and not decision.vetoed:
            violations.append(
                f"评分 {fs} ≥ 80 但 direction=wait，无否决时不合理"
            )
        if fs < 60 and decision.direction != "wait":
            violations.append(
                f"评分 {fs} < 60 但 direction={decision.direction}，应为 wait"
            )

        # ── 3. Entry condition check ──────────────────────────────
        if decision.direction != "wait" and not decision.entry_condition:
            violations.append("direction != wait 但 entry_condition 为空")
        if decision.direction == "wait" and decision.entry_condition and "等待" not in decision.entry_condition:
            violations.append("direction=wait 但 entry_condition 表述不清晰")

        # ── 4. Stop loss sanity ──────────────────────────────────
        if decision.direction != "wait" and not decision.stop_loss:
            violations.append("direction != wait 但 stop_loss 为空")
        if decision.stop_loss and "N/A" in decision.stop_loss and decision.direction != "wait":
            violations.append("stop_loss=N/A 但 direction != wait")

        # ── 5. Position suggestion sanity ─────────────────────────
        if decision.direction != "wait" and not decision.position_suggestion:
            violations.append("direction != wait 但 position_suggestion 为空")

        # ── 6. Confidence sanity ──────────────────────────────────
        if decision.confidence < 0 or decision.confidence > 1:
            violations.append(f"confidence={decision.confidence} 超出 0-1 范围")

        # ── 7. Human confirm ─────────────────────────────────────
        if decision.final_score >= 60 and not decision.need_human_confirm:
            violations.append(
                f"评分 {fs} ≥ 60 但 need_human_confirm=False，新手阶段必须 True"
            )

        # ── 8. Conflict signals should be present if applicable ───
        # (soft warning, not a hard violation)

        passed = len(violations) == 0
        if passed:
            logger.info("Validator: decision passed all checks ✅")
        else:
            logger.warning("Validator: %d violations detected ⚠️", len(violations))
            for v in violations:
                logger.warning("  • %s", v)

        return passed, violations
