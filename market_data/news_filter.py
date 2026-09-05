import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("spidy.news_filter")


class EconomicNewsFilter:
    """
    Macro Economic Event Shield.
    Safeguards crypto trading against sudden market manipulation, extreme slippage,
    and flash crashes caused by high-impact US economic announcements (CPI, FOMC, NFP).
    """

    def __init__(self, buffer_minutes: int = 30):
        self.buffer_seconds = buffer_minutes * 60
        self.events: List[Dict[str, any]] = []

    def register_event(self, name: str, timestamp: int, impact: str = "HIGH"):
        """Registers a scheduled economic announcement."""
        self.events.append({
            "name": name,
            "timestamp": timestamp,
            "impact": impact.upper()
        })
        logger.info(f"Registered macro event '{name}' at timestamp {timestamp} (Impact: {impact})")

    def is_in_high_impact_window(self, current_timestamp: Optional[int] = None) -> Tuple[bool, str]:
        """
        Evaluates whether current time falls within the pre- or post-event danger zone.
        Returns: (is_blocked, reason)
        """
        now = current_timestamp or int(time.time())

        for ev in self.events:
            if ev.get("impact") != "HIGH":
                continue

            ev_time = ev["timestamp"]
            diff = ev_time - now

            # If within pre-news window (e.g. 30 mins before)
            if 0 <= diff <= self.buffer_seconds:
                mins_left = int(diff / 60)
                reason = f"High-Impact Macro Event '{ev['name']}' in {mins_left}m. New entries frozen."
                return True, reason

            # If within post-news cooling window (e.g. 15 mins after)
            elif - (15 * 60) <= diff < 0:
                mins_passed = int(abs(diff) / 60)
                reason = f"Macro Event '{ev['name']}' occurred {mins_passed}m ago. Market settling."
                return True, reason

        return False, "Market conditions clear of high-impact macro news."
