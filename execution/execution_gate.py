"""ExecutionGate — 7 security checks that must ALL pass before any order is emitted.

Rules:
1. ENABLE_REAL_TRADING 是否为 true?
2. 是否处于 Testnet 或 Paper Trading?
3. API 是否禁止提现?
4. 是否设置 IP 白名单?
5. 是否有止损和失效条件?
6. 仓位是否超限?
7. 主模型和复核模型是否一致?

如果任何一项不满足，输出"不执行"。
"""

import logging
import re
from pathlib import Path
from typing import Any

from config import ExecutionConfig, RiskConfig
from execution.order_schemas import OrderPlan

logger = logging.getLogger("execution.gate")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GATE_OUTPUT_PATH = DATA_DIR / "execution_gate_output.json"


class ExecutionGate:
    """
    Execution gate — 7 mandatory checks before any order can be emitted.

    This is the FINAL layer before an order reaches the exchange.
    """

    def __init__(
        self,
        exec_cfg: ExecutionConfig | None = None,
        risk_cfg: RiskConfig | None = None,
    ) -> None:
        self.exec_cfg = exec_cfg or ExecutionConfig()
        self.risk_cfg = risk_cfg or RiskConfig()

    # ── Public API ──────────────────────────────────────────────────

    def approve(
        self,
        decision: dict[str, Any],
        audit_report: dict[str, Any] | None = None,
        validator_passed: bool | None = None,
        validator_violations: list[str] | None = None,
        capital: float = 10_000.0,
    ) -> OrderPlan:
        """
        Run the execution gate.

        Parameters
        ----------
        decision : dict
            ComprehensiveDecision from comprehensive_decision_agent.
        audit_report : dict, optional
            RiskAuditReport from risk audit agent.
        validator_passed : bool, optional
            Whether the validator agent approved the decision.
        validator_violations : list[str], optional
            Violations from validator agent.
        capital : float
            Current available capital in USDT.
        """
        logger.info("ExecutionGate: running 7 security checks")

        checks: list[dict[str, Any]] = []
        all_passed = True

        symbol = decision.get("symbol", "UNKNOWN")
        direction = decision.get("direction", "wait")
        final_score = decision.get("final_score", 0)
        confidence = decision.get("confidence", 0)
        entry_condition = decision.get("entry_condition", "")
        invalid_condition = decision.get("invalid_condition", "")
        stop_loss = decision.get("stop_loss", "")
        position_suggestion = decision.get("position_suggestion", "")
        vetoed = decision.get("vetoed", False)
        need_human = decision.get("need_human_confirm", True)
        market_state = decision.get("market_state", "range")

        # Extract position percentage from suggestion text
        pos_pct = self._extract_position_pct(position_suggestion)

        # ── Check 1: ENABLE_REAL_TRADING ─────────────────────────
        c1 = self._check_real_trading()
        checks.append(c1)
        if not c1["passed"]:
            all_passed = False

        # ── Check 2: Testnet or Paper ────────────────────────────
        c2 = self._check_mode()
        checks.append(c2)
        if not c2["passed"]:
            all_passed = False

        # ── Check 3: API withdrawal ──────────────────────────────
        c3 = self._check_api_withdrawal()
        checks.append(c3)
        if not c3["passed"]:
            all_passed = False

        # ── Check 4: IP whitelist ────────────────────────────────
        c4 = self._check_ip_whitelist()
        checks.append(c4)
        if not c4["passed"]:
            all_passed = False

        # ── Check 5: Stop loss & invalid condition ───────────────
        c5 = self._check_stop_and_invalid(
            stop_loss, invalid_condition, direction
        )
        checks.append(c5)
        if not c5["passed"]:
            all_passed = False

        # ── Check 6: Position limit ──────────────────────────────
        c6 = self._check_position_limit(pos_pct, direction, capital, symbol)
        checks.append(c6)
        if not c6["passed"]:
            all_passed = False

        # ── Check 7: Main model vs validator consistency ─────────
        c7 = self._check_model_consistency(
            vetoed, audit_report, validator_passed, validator_violations
        )
        checks.append(c7)
        if not c7["passed"]:
            all_passed = False

        # ── Compute quantity ─────────────────────────────────────
        if all_passed and direction in ("long", "short"):
            quantity, quantity_usdt = self._compute_quantity(
                pos_pct, capital
            )
        else:
            quantity = 0.0
            quantity_usdt = 0.0

        # ── Build output ─────────────────────────────────────────
        if not all_passed:
            failed = [c for c in checks if not c["passed"]]
            reasons = [f"检查{i+1}失败: {c['detail']}" for i, c in enumerate(failed)]
            reject_reason = "；".join(reasons) if reasons else "执行门检查未通过"
            plan = OrderPlan.rejected(
                reason=reject_reason,
                details=checks,
                mode=self.exec_cfg.execution_mode,
            )
        else:
            plan = OrderPlan(
                approved=True,
                execution_mode=self.exec_cfg.execution_mode,  # type: ignore
                symbol=symbol,
                direction=direction,  # type: ignore
                order_type="market",
                quantity=quantity,
                quantity_usdt=quantity_usdt,
                price=None,
                stop_loss=stop_loss,
                invalid_condition=invalid_condition,
                position_pct=round(pos_pct, 1),
                final_score=final_score,
                confidence=confidence,
            )

        # ── Always save output ───────────────────────────────────
        plan.reject_details = checks
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GATE_OUTPUT_PATH.write_text(plan.to_json())
        logger.info("Execution gate output saved to %s", GATE_OUTPUT_PATH)

        self._print(plan, checks)
        return plan

    # ── 7 individual checks ─────────────────────────────────────────

    @staticmethod
    def _check_real_trading() -> dict[str, Any]:
        """
        Check 1: ENABLE_REAL_TRADING 是否为 true?

        仅当 EXECUTION_MODE=real 时才强制检查此项。
        Paper 和 testnet 模式自动放行。
        """
        cfg = ExecutionConfig()
        if cfg.execution_mode != "real":
            return {"check_id": "real_trading", "passed": True, "detail": f"当前{cfg.mode_display}模式（{cfg.execution_mode}），无需确认真实交易开关"}
        if cfg.enable_real_trading:
            return {"check_id": "real_trading", "passed": True, "detail": f"ENABLE_REAL_TRADING=true，实盘模式确认"}
        return {
            "check_id": "real_trading",
            "passed": False,
            "detail": "ENABLE_REAL_TRADING 未设置为 true，但当前为实盘模式。请在 .env 中设置 ENABLE_REAL_TRADING=true 并重启后重试",
        }

    @staticmethod
    def _check_mode() -> dict[str, Any]:
        """
        Check 2: 是否处于 Testnet 或 Paper Trading?

        Current mode is read from EXECUTION_MODE config.
        """
        cfg = ExecutionConfig()
        mode = cfg.execution_mode
        if mode in ("paper", "testnet"):
            return {"check_id": "execution_mode", "passed": True, "detail": f"当前模式: {cfg.mode_display}({mode})"}
        if mode == "real":
            # Allow real mode, but warn
            return {"check_id": "execution_mode", "passed": True, "detail": "当前模式: 实盘(real) — 注意风险"}
        return {
            "check_id": "execution_mode",
            "passed": False,
            "detail": f"EXECUTION_MODE={mode} 无效，必须为 paper / testnet / real",
        }

    @staticmethod
    def _check_api_withdrawal() -> dict[str, Any]:
        """
        Check 3: API 是否禁止提现?

        In paper mode, this is auto-passed.
        In testnet, auto-passed.
        In real mode, we check EXCHANGE_API_WITHDRAWAL.
        """
        cfg = ExecutionConfig()
        if cfg.execution_mode in ("paper", "testnet"):
            return {"check_id": "api_withdrawal", "passed": True, "detail": f"{cfg.mode_display}模式，无需提现权限"}
        if cfg.exchange_api_withdrawal:
            return {"check_id": "api_withdrawal", "passed": False, "detail": "API Key 具有提现权限，存在资金安全风险。请创建仅限交易的 API Key 并禁用提现"}
        return {"check_id": "api_withdrawal", "passed": True, "detail": "API Key 提现已禁用，安全"}

    @staticmethod
    def _check_ip_whitelist() -> dict[str, Any]:
        """
        Check 4: 是否设置 IP 白名单?

        Paper/testnet → auto-passed.
        Real → must have IP whitelist.
        """
        cfg = ExecutionConfig()
        if cfg.execution_mode in ("paper", "testnet"):
            return {"check_id": "ip_whitelist", "passed": True, "detail": f"{cfg.mode_display}模式，无需 IP 白名单"}
        if cfg.ip_whitelist_enabled:
            return {"check_id": "ip_whitelist", "passed": True, "detail": f"IP 白名单已设置: {cfg.exchange_ip_whitelist}"}
        return {
            "check_id": "ip_whitelist",
            "passed": False,
            "detail": "实盘模式但未设置 IP 白名单。请在交易所后台设置 IP 白名单，并在 .env 中配置 EXCHANGE_IP_WHITELIST",
        }

    @staticmethod
    def _check_stop_and_invalid(
        stop_loss: str, invalid_condition: str, direction: str
    ) -> dict[str, Any]:
        """
        Check 5: 是否有止损和失效条件?

        direction=wait → auto-passed.
        stop_loss_required → must have stop_loss.
        invalid_cond_required → must have invalid_condition.
        """
        cfg = ExecutionConfig()

        if direction == "wait":
            return {"check_id": "stop_and_invalid", "passed": True, "detail": "方向为等待，无需止损条件"}

        issues: list[str] = []

        if cfg.stop_loss_required and (not stop_loss or stop_loss in ("", "N/A")):
            issues.append("止损条件为空。必须设置明确的止损条件（价格/ATR/均线）")

        if cfg.invalid_cond_required and (not invalid_condition or invalid_condition in ("", "N/A", "当前无有效计划")):
            issues.append("失效条件为空。必须设置明确的失效条件（价格破位/趋势反转/新闻证伪）")

        if issues:
            return {"check_id": "stop_and_invalid", "passed": False, "detail": "；".join(issues)}

        return {"check_id": "stop_and_invalid", "passed": True, "detail": f"止损={stop_loss}，失效条件={invalid_condition}"}

    @staticmethod
    def _check_position_limit(
        pos_pct: float, direction: str, capital: float, symbol: str
    ) -> dict[str, Any]:
        """
        Check 6: 仓位是否超限?

        - direction=wait → auto-passed (0%)
        - pos_pct > POSITION_LIMIT_PCT → fail
        - pos_pct > max_single (50% of limit) → warning
        """
        cfg = ExecutionConfig()

        if direction == "wait":
            return {"check_id": "position_limit", "passed": True, "detail": "方向为等待，无需检查仓位"}

        limit_pct = cfg.position_limit_pct
        max_single = limit_pct * 0.75  # e.g. 20% → single max 15%

        if pos_pct <= 0:
            return {"check_id": "position_limit", "passed": False, "detail": f"仓位{pos_pct:.1f}%≤0，仓位建议无效"}

        if pos_pct > limit_pct:
            return {
                "check_id": "position_limit",
                "passed": False,
                "detail": f"仓位{pos_pct:.1f}%超过总仓位上限{limit_pct:.0f}%。建议降至{max_single:.0f}%以内",
            }

        if pos_pct > max_single:
            return {
                "check_id": "position_limit",
                "passed": False,
                "detail": f"单标仓位{pos_pct:.1f}%超过推荐上限{max_single:.0f}%。请降至{max_single:.0f}%以下",
            }

        usdt_value = pos_pct / 100 * capital
        return {"check_id": "position_limit", "passed": True, "detail": f"仓位{pos_pct:.1f}%（≈{usdt_value:.0f} USDT）合规，上限{limit_pct:.0f}%"}

    @staticmethod
    def _check_model_consistency(
        vetoed: bool,
        audit_report: dict[str, Any] | None,
        validator_passed: bool | None,
        validator_violations: list[str] | None,
    ) -> dict[str, Any]:
        """
        Check 7: 主模型和复核模型是否一致?

        Checks:
        - decision.vetoed → 风控否决
        - audit_report.approved → 风控审查通过?
        - validator_passed → 复核Agent通过?
        """
        issues: list[str] = []

        # Check 7a: Decision vetoed
        if vetoed:
            issues.append("主决策已被否决，不执行")

        # Check 7b: Risk audit
        if audit_report is not None:
            audit_approved = audit_report.get("approved", False)
            if not audit_approved:
                veto_reason = audit_report.get("veto_reason", "风控审查未通过")
                issues.append(f"风控审查否决: {veto_reason}")

        # Check 7c: Validator agent
        if validator_passed is not None and not validator_passed:
            v_list = validator_violations or []
            if v_list:
                issues.append(f"复核Agent检测到{len(v_list)}项违规: {'; '.join(v_list[:3])}")
            else:
                issues.append("复核Agent判定决策不合规")

        if issues:
            return {"check_id": "model_consistency", "passed": False, "detail": "；".join(issues)}

        return {"check_id": "model_consistency", "passed": True, "detail": "主模型与复核模型一致，风控审查通过"}

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_position_pct(suggestion: str) -> float:
        """Extract the first percentage number from position suggestion text."""
        if not suggestion:
            return 0.0
        numbers = re.findall(r'(\d+(?:\.\d+)?)%', suggestion)
        return float(numbers[0]) if numbers else 0.0

    @staticmethod
    def _compute_quantity(pos_pct: float, capital: float) -> tuple[float, float]:
        """Compute order quantity and USDT value."""
        usdt_value = pos_pct / 100 * capital
        return usdt_value, usdt_value

    @staticmethod
    def _print(plan: OrderPlan, checks: list[dict[str, Any]]) -> None:
        status = "✅ 执行通过" if plan.approved else "🛑 不执行"
        print(f"\n─── 执行门 [{status}] ───")
        print(f"模式: {plan.execution_mode}")
        if plan.approved:
            print(f"标的: {plan.symbol} | 方向: {plan.direction.upper()}")
            print(f"数量: {plan.quantity:.6f} ({plan.quantity_usdt:.2f} USDT)")
            print(f"仓位: {plan.position_pct:.1f}%")
            print(f"止损: {plan.stop_loss}")
            print(f"失效条件: {plan.invalid_condition}")
        else:
            print(f"拒绝原因: {plan.reject_reason}")
        print("── 检查明细 ──")
        for c in checks:
            s = "✅" if c["passed"] else "❌"
            print(f"  {s} {c['detail'][:80]}")
        print(plan.disclaimer())
