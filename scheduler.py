"""Scheduler — orchestrates periodic agent runs."""

import logging
import time
from datetime import datetime, timezone

from config import SchedulerConfig

logger = logging.getLogger(__name__)


class Scheduler:
    """Simple loop-based scheduler for periodic trading cycles."""

    def __init__(self) -> None:
        self.cfg = SchedulerConfig()
        self._running = False

    @property
    def interval_seconds(self) -> int:
        return self.cfg.check_interval_minutes * 60

    def start(self, cycle_fn, symbols: list[str] | None = None) -> None:
        """Start the scheduling loop."""
        self._running = True
        symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        logger.info("Scheduler started (interval=%ds, symbols=%s)",
                    self.interval_seconds, symbols)

        while self._running:
            cycle_start = time.monotonic()
            now = datetime.now(timezone.utc)
            logger.info("=== Cycle %s ===", now.isoformat())

            for sym in symbols:
                try:
                    cycle_fn(sym)
                except Exception as e:
                    logger.error("Cycle failed for %s: %s", sym, e)

            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, self.interval_seconds - elapsed)
            logger.info("Cycle done in %.1fs, sleeping %.1fs", elapsed, sleep_time)
            time.sleep(sleep_time)

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped")
