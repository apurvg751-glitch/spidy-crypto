from typing import Optional, Sequence
from pydantic import BaseModel
from market_data.models import Candle


class RetestEvent(BaseModel):
    detected: bool = False
    direction: Optional[str] = None          # "BULLISH" (retesting support) or "BEARISH" (retesting resistance)
    retested_level: float = 0.0
    touch_price: float = 0.0
    distance_to_level: float = 0.0
    tolerance: float = 0.0
    bars_since_break: int = 0
    confirmed: bool = False
    candle_index: int = -1
    candle_time: int = 0
    description: str = ""


class RetestEngine:
    """
    Evaluates whether price is executing a valid retest of a broken structure level, OB, or sweep level:
    BOS/Sweep -> meaningful level -> price returns -> retest within ATR tolerance -> confirmation.
    """

    @staticmethod
    def evaluate_retest(
        candles: Sequence[Candle],
        level: float,
        direction: str,                      # "LONG" (testing level from above) or "SHORT" (testing level from below)
        break_bar_idx: int,
        atr: float,
        tolerance_atr: float = 0.35,
        max_bars_since_break: int = 12
    ) -> RetestEvent:
        if len(candles) < 2 or break_bar_idx < 0 or break_bar_idx >= len(candles):
            return RetestEvent()

        n = len(candles)
        bars_since_break = (n - 1) - break_bar_idx

        # Expiration check
        if bars_since_break > max_bars_since_break or bars_since_break < 1:
            return RetestEvent(
                description=f"Retest outside validity window (bars elapsed: {bars_since_break})"
            )

        tolerance = max(atr * tolerance_atr, level * 0.0005)
        curr = candles[-1]

        if direction == "LONG":
            # For LONG: Broken level should now act as support.
            # Price pulls back down to level: low <= level + tolerance and high >= level - tolerance
            is_touch = (curr.low <= level + tolerance) and (curr.close >= level - tolerance)
            if is_touch:
                dist = abs(curr.low - level)
                # Rejection confirmation: candle closes above level or has bottom wick
                confirmed = (curr.close >= level) or (curr.lower_wick >= curr.total_range * 0.20)
                return RetestEvent(
                    detected=True,
                    direction="BULLISH",
                    retested_level=level,
                    touch_price=curr.low,
                    distance_to_level=round(dist, 4),
                    tolerance=round(tolerance, 4),
                    bars_since_break=bars_since_break,
                    confirmed=confirmed,
                    candle_index=n - 1,
                    candle_time=curr.time,
                    description=f"Bullish retest of support {level:.2f} within ±{tolerance:.2f} (bars: {bars_since_break})"
                )

        elif direction == "SHORT":
            # For SHORT: Broken level should now act as resistance.
            # Price pulls back up to level: high >= level - tolerance and low <= level + tolerance
            is_touch = (curr.high >= level - tolerance) and (curr.close <= level + tolerance)
            if is_touch:
                dist = abs(curr.high - level)
                # Rejection confirmation: candle closes below level or has top wick
                confirmed = (curr.close <= level) or (curr.upper_wick >= curr.total_range * 0.20)
                return RetestEvent(
                    detected=True,
                    direction="BEARISH",
                    retested_level=level,
                    touch_price=curr.high,
                    distance_to_level=round(dist, 4),
                    tolerance=round(tolerance, 4),
                    bars_since_break=bars_since_break,
                    confirmed=confirmed,
                    candle_index=n - 1,
                    candle_time=curr.time,
                    description=f"Bearish retest of resistance {level:.2f} within ±{tolerance:.2f} (bars: {bars_since_break})"
                )

        return RetestEvent()
