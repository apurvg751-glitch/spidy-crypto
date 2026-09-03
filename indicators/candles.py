from typing import Sequence
from market_data.models import Candle


def is_bullish_engulfing(prev: Candle, curr: Candle) -> bool:
    """
    Bullish Engulfing:
    - Previous candle is bearish
    - Current candle is bullish
    - Current body completely engulfs previous body
    """
    if not prev.is_bearish or not curr.is_bullish:
        return False
    return (curr.close >= prev.open) and (curr.open <= prev.close) and (curr.body_size > prev.body_size * 0.8)


def is_bearish_engulfing(prev: Candle, curr: Candle) -> bool:
    """
    Bearish Engulfing:
    - Previous candle is bullish
    - Current candle is bearish
    - Current body completely engulfs previous body
    """
    if not prev.is_bullish or not curr.is_bearish:
        return False
    return (curr.close <= prev.open) and (curr.open >= prev.close) and (curr.body_size > prev.body_size * 0.8)


def is_bullish_pinbar(c: Candle) -> bool:
    """
    Bullish Pin Bar / Hammer:
    - Lower wick >= 2x body size
    - Upper wick <= 25% of total range
    """
    if c.total_range <= 0:
        return False
    body = max(c.body_size, 1e-6)
    return (c.lower_wick >= body * 1.8) and (c.upper_wick <= c.total_range * 0.3)


def is_bearish_pinbar(c: Candle) -> bool:
    """
    Bearish Pin Bar / Shooting Star:
    - Upper wick >= 2x body size
    - Lower wick <= 25% of total range
    """
    if c.total_range <= 0:
        return False
    body = max(c.body_size, 1e-6)
    return (c.upper_wick >= body * 1.8) and (c.lower_wick <= c.total_range * 0.3)


def is_rejection_candle(c: Candle, direction: str) -> bool:
    """
    General Rejection candle check:
    - For LONG: lower wick >= 25% of total range OR bullish pinbar
    - For SHORT: upper wick >= 25% of total range OR bearish pinbar
    """
    if c.total_range <= 0:
        return False
    if direction == "LONG":
        return (c.lower_wick >= c.total_range * 0.25) or is_bullish_pinbar(c)
    elif direction == "SHORT":
        return (c.upper_wick >= c.total_range * 0.25) or is_bearish_pinbar(c)
    return False


def detect_candle_confirmation(candles: Sequence[Candle], direction: str) -> tuple[bool, str]:
    """
    Evaluates recent candles (last 2-3 bars) for deterministic reversal patterns.
    Returns (confirmed, description).
    """
    if len(candles) < 2:
        return False, "Insufficient candle history"

    curr = candles[-1]
    prev = candles[-2]

    if direction == "LONG":
        if is_bullish_engulfing(prev, curr):
            return True, "Bullish Engulfing candle"
        if is_bullish_pinbar(curr):
            return True, "Bullish Pin Bar / Hammer"
        if curr.is_bullish and curr.lower_wick >= curr.total_range * 0.25:
            return True, "Bullish Rejection candle with bottom wick"
    elif direction == "SHORT":
        if is_bearish_engulfing(prev, curr):
            return True, "Bearish Engulfing candle"
        if is_bearish_pinbar(curr):
            return True, "Bearish Pin Bar / Shooting Star"
        if curr.is_bearish and curr.upper_wick >= curr.total_range * 0.25:
            return True, "Bearish Rejection candle with top wick"

    return False, "No clean candle confirmation"
