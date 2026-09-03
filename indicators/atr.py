from typing import Sequence
from market_data.models import Candle


def calculate_atr(candles: Sequence[Candle], period: int = 14) -> float:
    """
    Calculates the Average True Range (ATR) for a given sequence of candles.
    TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
    """
    if len(candles) < period + 1:
        # Fallback to simple average high - low if insufficient history
        if not candles:
            return 1.0
        return sum(c.high - c.low for c in candles) / len(candles)

    # Calculate True Ranges
    true_ranges = []
    for i in range(1, len(candles)):
        current = candles[i]
        prev = candles[i - 1]
        tr = max(
            current.high - current.low,
            abs(current.high - prev.close),
            abs(current.low - prev.close)
        )
        true_ranges.append(tr)

    # Initial ATR is SMA of first 'period' true ranges
    atr = sum(true_ranges[:period]) / period

    # Wilder's Smoothing for subsequent values
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    return max(atr, 1e-6)
