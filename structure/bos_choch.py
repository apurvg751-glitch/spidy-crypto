from typing import Optional, Sequence, Literal
from pydantic import BaseModel
from market_data.models import Candle
from .swings import SwingPoint


class StructureBreakEvent(BaseModel):
    detected: bool = False
    event_type: Optional[Literal["BOS", "CHOCH"]] = None
    direction: Optional[Literal["BULLISH", "BEARISH"]] = None
    broken_level: float = 0.0
    break_price: float = 0.0
    reference_swing: Optional[SwingPoint] = None
    strength: Literal["NORMAL", "STRONG"] = "NORMAL"
    close_confirmed: bool = False
    candle_index: int = -1
    candle_time: int = 0
    description: str = ""


class BosChochEngine:
    """Detects deterministic BOS (Break of Structure) and CHoCH (Change of Character)."""

    @staticmethod
    def detect(
        candles: Sequence[Candle],
        swings: list[SwingPoint],
        search_bars: int = 8,
        trend_bias: str = "Neutral"
    ) -> StructureBreakEvent:
        if len(candles) < 3 or not swings:
            return StructureBreakEvent()

        n = len(candles)
        start_bar = max(0, n - search_bars)

        valid_swings = [s for s in swings if s.index < start_bar]
        if not valid_swings:
            valid_swings = [s for s in swings if s.index < n - 1]
        if not valid_swings:
            return StructureBreakEvent()

        recent_highs = [s for s in valid_swings if s.point_type == "HIGH"]
        recent_lows = [s for s in valid_swings if s.point_type == "LOW"]

        for bar_idx in range(start_bar, n):
            c = candles[bar_idx]

            # Bullish Break (above a swing high)
            for s_high in reversed(recent_highs[-3:]):
                if c.close > s_high.price:
                    # Determine whether BOS (continuation) or CHoCH (reversal from bearish)
                    is_choch = (trend_bias == "Bearish" or s_high.structure_label == "LH")
                    event_type = "CHOCH" if is_choch else "BOS"
                    is_strong = (c.body_size > c.total_range * 0.6)

                    desc = (
                        f"Bullish {event_type} above {s_high.price:.2f} "
                        f"(closed {c.close:.2f}, swing idx {s_high.index})"
                    )
                    return StructureBreakEvent(
                        detected=True,
                        event_type=event_type,
                        direction="BULLISH",
                        broken_level=s_high.price,
                        break_price=c.close,
                        reference_swing=s_high,
                        strength="STRONG" if is_strong else "NORMAL",
                        close_confirmed=True,
                        candle_index=bar_idx,
                        candle_time=c.time,
                        description=desc
                    )

            # Bearish Break (below a swing low)
            for s_low in reversed(recent_lows[-3:]):
                if c.close < s_low.price:
                    # Determine whether BOS or CHoCH
                    is_choch = (trend_bias == "Bullish" or s_low.structure_label == "HL")
                    event_type = "CHOCH" if is_choch else "BOS"
                    is_strong = (c.body_size > c.total_range * 0.6)

                    desc = (
                        f"Bearish {event_type} below {s_low.price:.2f} "
                        f"(closed {c.close:.2f}, swing idx {s_low.index})"
                    )
                    return StructureBreakEvent(
                        detected=True,
                        event_type=event_type,
                        direction="BEARISH",
                        broken_level=s_low.price,
                        break_price=c.close,
                        reference_swing=s_low,
                        strength="STRONG" if is_strong else "NORMAL",
                        close_confirmed=True,
                        candle_index=bar_idx,
                        candle_time=c.time,
                        description=desc
                    )

        return StructureBreakEvent()


# Maintain backward compatibility with structure/bos.py
detect_bos_choch = BosChochEngine.detect
