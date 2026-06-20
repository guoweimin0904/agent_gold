"""Kill switch — emergency stop all trading."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class KillSwitch:
    """Emergency stop — halts all trading until manually reset."""

    def __init__(self) -> None:
        self._active = False
        self._reason = ""
        self._triggered_at: str | None = None
        self._state_path = LOG_DIR / "kill_switch.json"

    @property
    def is_active(self) -> bool:
        return self._active

    def trigger(self, reason: str) -> dict[str, Any]:
        """Activate the kill switch."""
        self._active = True
        self._reason = reason
        self._triggered_at = datetime.now(timezone.utc).isoformat()
        self._persist()
        logger.warning("KILL SWITCH TRIGGERED: %s", reason)
        return {"status": "halted", "reason": reason, "time": self._triggered_at}

    def reset(self) -> dict[str, Any]:
        """Deactivate the kill switch."""
        self._active = False
        self._reason = ""
        self._triggered_at = None
        self._persist()
        logger.info("Kill switch reset — trading resumed")
        return {"status": "resumed"}

    def check_before_trade(self, market_condition: str | None = None) -> bool:
        """Check if trading is allowed. Returns True if OK to trade."""
        if self._active:
            logger.warning("Trade blocked by kill switch: %s", self._reason)
            return False
        # Future: integrate with circuit breakers, sudden volatility detection
        return True

    def _persist(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"active": self._active, "reason": self._reason, "triggered_at": self._triggered_at}
        self._state_path.write_text(json.dumps(data, indent=2))
