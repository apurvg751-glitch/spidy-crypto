from typing import Optional
from pydantic import BaseModel
from market_data.models import Candle


class DisplacementResult(BaseModel):
    detected: bool = False
    direction: str = "NONE"      # "BULLISH", "BEARISH", "NONE"
    body_ratio: float = 0.0      # Body size / Total candle range
    expansion_ratio: float = 0.0 # Range / Average Range of last 10 candles
    has_fvg: bool = False
    description: str = "No institutional displacement detected"


class DisplacementEngine:
    """
    Detects aggressive institutional displacement candles.
    True smart money entries produce:
    1. Large real bodies (body_ratio >= 0.55)
    2. Expansive range compared to recent background volatility (expansion_ratio >= 1.20)
    3. Minimal wicks on the expansion side
    """

    @staticmethod
    def evaluate(candles: list[Candle], lookback_atr: int = 14) -> DisplacementResult:
        if not candles or len(candles) < 5:
            return DisplacementResult()

        target_candle = candles[-1]
        c_range = target_candle.high - target_candle.low
        if c_range <= 0:
            return DisplacementResult()

        body = abs(target_candle.close - target_candle.open)
        body_ratio = body / c_range

        # Calculate average candle range of previous 10 candles
        prev_ranges = [(c.high - c.low) for c in candles[-11:-1]]
        avg_range = (sum(prev_ranges) / len(prev_ranges)) if prev_ranges else c_range
        expansion_ratio = c_range / max(avg_range, 1e-4)

        is_bullish = target_candle.close > target_candle.open
        direction = "BULLISH" if is_bullish else "BEARISH"

        # Check for immediate FVG creation with candle -3 if at least 3 candles exist
        has_fvg = False
        if len(candles) >= 3:
            c1 = candles[-3]
            c3 = target_candle
            if is_bullish and c3.low > c1.high:
                has_fvg = True
            elif not is_bullish and c3.high < c1.low:
                has_fvg = True

        # Institutional Displacement Criteria:
        # 1. Body must be at least 55% of the total bar (not a doji or rejection wick)
        # 2. Range must be at least 1.15x larger than recent baseline average
        is_displacement = (body_ratio >= 0.55) and (expansion_ratio >= 1.15)

        desc = (
            f"Institutional {direction} Displacement (Body: {body_ratio*100:.0f}%, "
            f"Expansion: {expansion_ratio:.2f}x avg, FVG: {'Yes' if has_fvg else 'No'})"
            if is_displacement else
            f"Normal price action (Body: {body_ratio*100:.0f}%, Expansion: {expansion_ratio:.2f}x avg)"
        )

        return DisplacementResult(
            detected=is_displacement,
            direction=direction if is_displacement else "NONE",
            body_ratio=round(body_ratio, 2),
            expansion_ratio=round(expansion_ratio, 2),
            has_fvg=has_fvg,
            description=desc
        )
