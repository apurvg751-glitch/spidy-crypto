from typing import Optional, Sequence
from pydantic import BaseModel
from market_data.models import Candle
from .swings import SwingPoint


class BreakOfStructure(BaseModel):
    detected: bool = False
    direction: Optional[str] = None       # BULLISH or BEARISH
    broken_level: float = 0.0             # The swing level broken
    close_price: float = 0.0              # Candle close establishing the BOS
    candle_index: int = -1
    candle_time: int = 0
    description: str = ""


def detect_bos(
    candles: Sequence[Candle],
    swings: list[SwingPoint],
    search_bars: int = 6
) -> BreakOfStructure:
    """
    Detects if any recent candle (within the last `search_bars`) closed beyond a prior swing:
    - Bullish BOS: Candle close > prior swing high
    - Bearish BOS: Candle close < prior swing low
    """
    if len(candles) < 10 or not swings:
        return BreakOfStructure()

    n = len(candles)
    start_bar = max(0, n - search_bars)

    valid_swings = [s for s in swings if s.index < start_bar]
    if not valid_swings:
        valid_swings = [s for s in swings if s.index < n - 1]

    if not valid_swings:
        return BreakOfStructure()

    recent_highs = [s for s in valid_swings if s.point_type == "HIGH"]
    recent_lows = [s for s in valid_swings if s.point_type == "LOW"]

    for bar_idx in range(n - 1, start_bar - 1, -1):
        c = candles[bar_idx]

        # Bullish BOS: candle closed above a prior swing high
        for s_high in reversed(recent_highs[-3:]):
            if c.close > s_high.price:
                return BreakOfStructure(
                    detected=True,
                    direction="BULLISH",
                    broken_level=s_high.price,
                    close_price=c.close,
                    candle_index=bar_idx,
                    candle_time=c.time,
                    description=f"Bullish BOS above {s_high.price:.2f} (closed {c.close:.2f})"
                )

        # Bearish BOS: candle closed below a prior swing low
        for s_low in reversed(recent_lows[-3:]):
            if c.close < s_low.price:
                return BreakOfStructure(
                    detected=True,
                    direction="BEARISH",
                    broken_level=s_low.price,
                    close_price=c.close,
                    candle_index=bar_idx,
                    candle_time=c.time,
                    description=f"Bearish BOS below {s_low.price:.2f} (closed {c.close:.2f})"
                )

    return BreakOfStructure()
