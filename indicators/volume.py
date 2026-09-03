from typing import Sequence
from market_data.models import Candle


def calculate_volume_sma(candles: Sequence[Candle], period: int = 20) -> float:
    """Calculates Simple Moving Average of Volume."""
    if not candles:
        return 0.0
    usable = candles[-period:] if len(candles) >= period else candles
    return sum(c.volume for c in usable) / len(usable)


def calculate_rvol(candles: Sequence[Candle], period: int = 20) -> float:
    """Calculates Relative Volume (latest candle volume / volume SMA)."""
    if not candles:
        return 1.0
    sma = calculate_volume_sma(candles[:-1], period=period)
    if sma <= 0:
        return 1.0
    latest_vol = candles[-1].volume
    return latest_vol / sma


def is_volume_confirmed(candles: Sequence[Candle], period: int = 20, threshold: float = 1.15) -> bool:
    """Checks if the latest candle's volume is significantly higher than average."""
    return calculate_rvol(candles, period=period) >= threshold
