import time
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel


class SessionFilterResult(BaseModel):
    session_name: str
    is_peak_institutional: bool
    is_trading_allowed: bool
    min_confirmations_required: int
    min_score_required: int
    session_label: str
    description: str


class SessionFilterEngine:
    """
    Classifies market time into high-liquidity Institutional Kill Zones vs.
    low-liquidity off-peak chop hours.
    Permits new trade entries strictly during London Open and New York Open Killzones.
    """

    @staticmethod
    def evaluate_session(ts: Optional[int] = None) -> SessionFilterResult:
        now_utc = datetime.fromtimestamp(ts or int(time.time()), tz=timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute
        time_dec = hour + (minute / 60.0)

        # 1. London Open Kill Zone: 07:00 to 11:00 UTC (12:30 to 16:30 IST)
        if 7.0 <= time_dec <= 11.0:
            return SessionFilterResult(
                session_name="LONDON_OPEN",
                is_peak_institutional=True,
                is_trading_allowed=True,
                min_confirmations_required=4,
                min_score_required=70,
                session_label="🇬🇧 London Open Killzone (Institutional Expansion)",
                description="High liquidity and institutional manipulation sweeps. Trading authorized."
            )

        # 2. New York Open Kill Zone: 12:00 to 17:00 UTC (17:30 to 22:30 IST)
        elif 12.0 <= time_dec <= 17.0:
            return SessionFilterResult(
                session_name="NEW_YORK_OPEN",
                is_peak_institutional=True,
                is_trading_allowed=True,
                min_confirmations_required=4,
                min_score_required=70,
                session_label="🇺🇸 New York Open Killzone (Major Trend Expansion)",
                description="Peak global volume, Wall Street algorithms, and rapid target hits. Trading authorized."
            )

        # 3. Asian Session: 00:00 to 06:00 UTC (05:30 to 11:30 IST)
        elif 0.0 <= time_dec < 6.0:
            return SessionFilterResult(
                session_name="ASIAN_SESSION",
                is_peak_institutional=False,
                is_trading_allowed=False,
                min_confirmations_required=6,
                min_score_required=95,
                session_label="🌏 Asian Range Accumulation (Entries Blocked)",
                description="Low-volume range formation and fakeouts. New entries strictly blocked to protect capital."
            )

        # 4. Off-Peak / Dead Zone Chop (All other off-hours)
        else:
            return SessionFilterResult(
                session_name="OFF_PEAK_CHOP",
                is_peak_institutional=False,
                is_trading_allowed=False,
                min_confirmations_required=6,
                min_score_required=95,
                session_label="🌙 Off-Peak Window (Entries Blocked)",
                description="Thin liquidity and wide spreads. New entries strictly blocked to protect capital."
            )

