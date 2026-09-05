import time
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel


class SessionFilterResult(BaseModel):
    session_name: str
    is_peak_institutional: bool
    min_confirmations_required: int
    min_score_required: int
    session_label: str
    description: str


class SessionFilterEngine:
    """
    Classifies market time into high-liquidity Institutional Kill Zones vs.
    low-liquidity off-peak chop hours.
    """

    @staticmethod
    def evaluate_session(ts: Optional[int] = None) -> SessionFilterResult:
        now_utc = datetime.fromtimestamp(ts or int(time.time()), tz=timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute
        time_dec = hour + (minute / 60.0)

        # 1. London Open Kill Zone: 07:00 to 10:30 UTC (12:30 to 16:00 IST)
        if 7.0 <= time_dec <= 10.5:
            return SessionFilterResult(
                session_name="LONDON_OPEN",
                is_peak_institutional=True,
                min_confirmations_required=4,
                min_score_required=70,
                session_label="🇬🇧 London Open (Institutional Expansion)",
                description="High liquidity and institutional manipulation sweeps."
            )

        # 2. New York Open Kill Zone: 13:00 to 17:30 UTC (18:30 to 23:00 IST)
        elif 13.0 <= time_dec <= 17.5:
            return SessionFilterResult(
                session_name="NEW_YORK_OPEN",
                is_peak_institutional=True,
                min_confirmations_required=4,
                min_score_required=70,
                session_label="🇺🇸 New York Open (Major Trend Expansion)",
                description="Peak global volume, Wall Street algorithms, and rapid target hits."
            )

        # 3. Off-Peak / Asian Session: 17:30 to 07:00 UTC (23:00 to 12:30 IST)
        else:
            return SessionFilterResult(
                session_name="OFF_PEAK_CHOP",
                is_peak_institutional=False,
                min_confirmations_required=5,  # Stricter criteria during thin liquidity
                min_score_required=80,
                session_label="🌙 Off-Peak Window (Strict A+ Confluence Only)",
                description="Lower volume and wider spreads. Requires high-conviction confluences."
            )
