from datetime import datetime, timezone, timedelta
from typing import Optional, List
from pydantic import BaseModel
from market_data.models import Candle


class KillZoneStatus(BaseModel):
    session_name: str          # "ASIAN_SESSION", "LONDON_OPEN", "NEW_YORK_OPEN", "OFF_HOURS"
    is_active_kill_zone: bool
    is_tradeable: bool = False
    description: str
    confidence_multiplier: float
    asian_high: Optional[float] = None
    asian_low: Optional[float] = None
    ist_time_str: str


class KillZoneEngine:
    """
    Institutional Session & Macro Kill Zone Timing Engine.
    Aligns trading signals with high-volume institutional liquidity windows.
    Times in IST (UTC+5:30):
      - Asian Session: 05:30 - 11:30 IST (Liquidity Accumulation - Entries Blocked)
      - London Open (Judas Sweep & Clean Expansion): 12:30 - 16:30 IST
      - New York AM Open (Major Institutional Expansion): 17:30 - 22:30 IST
      - Off-Hours / Dead Liquidity: 22:30 - 05:30 IST (Entries Blocked)
    """

    IST_OFFSET = timedelta(hours=5, minutes=30)

    @classmethod
    def get_current_session(cls, current_utc_time: Optional[datetime] = None) -> tuple[str, bool, str, float]:
        now_utc = current_utc_time or datetime.now(timezone.utc)
        now_ist = now_utc + cls.IST_OFFSET

        hour = now_ist.hour
        minute = now_ist.minute
        time_decimal = hour + (minute / 60.0)

        # 1. Asian Session (05:30 - 11:30 IST)
        if 5.5 <= time_decimal < 11.5:
            return (
                "ASIAN_SESSION",
                False,
                "Asian Session (Liquidity Accumulation & Range Creation - Entries Blocked)",
                0.60
            )

        # 2. London Open Kill Zone (12:30 - 16:30 IST)
        elif 12.5 <= time_decimal < 16.5:
            return (
                "LONDON_OPEN",
                True,
                "London Open Kill Zone (Judas Swing & Clean Expansion)",
                1.25
            )

        # 3. New York AM Open Kill Zone (17:30 - 22:30 IST)
        elif 17.5 <= time_decimal < 22.5:
            return (
                "NEW_YORK_OPEN",
                True,
                "New York AM Kill Zone (Major Institutional Expansion & Trend Continuation)",
                1.30
            )

        # 4. Off-Hours / Low Liquidity Window (Entries Blocked)
        else:
            return (
                "OFF_HOURS",
                False,
                "Off-Hours / Low Institutional Volume Window (Entries Blocked)",
                0.50
            )


    @classmethod
    def calculate_asian_range(cls, candles_15m: List[Candle]) -> tuple[Optional[float], Optional[float]]:
        """Calculates Asian Session High (ASH) and Asian Session Low (ASL) from historical candles."""
        if not candles_15m or len(candles_15m) < 8:
            return None, None

        asian_candles = []
        for c in candles_15m[-32:]:  # Last ~8 hours of 15m candles
            dt_ist = datetime.fromtimestamp(c.time, tz=timezone.utc) + cls.IST_OFFSET
            time_dec = dt_ist.hour + (dt_ist.minute / 60.0)
            if 5.5 <= time_dec < 11.5:
                asian_candles.append(c)

        if not asian_candles:
            # Fallback to general recent swing range
            highs = [c.high for c in candles_15m[-16:]]
            lows = [c.low for c in candles_15m[-16:]]
            return max(highs), min(lows)

        ash = max(c.high for c in asian_candles)
        asl = min(c.low for c in asian_candles)
        return ash, asl

    @classmethod
    def evaluate(cls, candles_15m: Optional[List[Candle]] = None, current_utc_time: Optional[datetime] = None) -> KillZoneStatus:
        now_utc = current_utc_time or datetime.now(timezone.utc)
        now_ist = now_utc + cls.IST_OFFSET
        session_name, is_active, desc, mult = cls.get_current_session(now_utc)

        ash, asl = None, None
        if candles_15m:
            ash, asl = cls.calculate_asian_range(candles_15m)

        return KillZoneStatus(
            session_name=session_name,
            is_active_kill_zone=is_active,
            is_tradeable=(session_name in ("LONDON_OPEN", "NEW_YORK_OPEN")),
            description=desc,
            confidence_multiplier=mult,
            asian_high=ash,
            asian_low=asl,
            ist_time_str=now_ist.strftime("%I:%M %p IST")
        )
