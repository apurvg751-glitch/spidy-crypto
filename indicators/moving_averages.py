from typing import Sequence, Literal
from market_data.models import Candle


def calculate_ema(prices: Sequence[float], period: int) -> list[float]:
    """
    Calculates Exponential Moving Average series.
    Adapts to available sample length if len(prices) < period.
    """
    if not prices:
        return [0.0]

    effective_period = min(period, len(prices))
    if effective_period <= 1:
        return list(prices)

    multiplier = 2.0 / (effective_period + 1)
    # Initial SMA over effective period
    sma = sum(prices[:effective_period]) / effective_period
    ema_series = [sma]

    for p in prices[effective_period:]:
        ema = (p - ema_series[-1]) * multiplier + ema_series[-1]
        ema_series.append(ema)

    return ema_series


def get_trend_bias(candles: Sequence[Candle]) -> Literal["Bullish", "Bearish", "Neutral"]:
    """
    Evaluates higher-timeframe trend bias using fast/slow EMAs and price action.
    Returns 'Bullish', 'Bearish', or 'Neutral'.
    """
    if not candles:
        return "Neutral"
    if len(candles) < 15:
        return "Bullish" if candles[-1].close >= candles[0].close else "Bearish"

    closes = [c.close for c in candles]
    p_fast = min(20, max(5, len(closes) // 3))
    p_slow = min(50, max(10, len(closes) * 2 // 3))

    ema_fast = calculate_ema(closes, p_fast)[-1]
    ema_slow = calculate_ema(closes, p_slow)[-1]
    latest_close = closes[-1]

    if latest_close >= ema_fast and ema_fast >= ema_slow:
        return "Bullish"
    elif latest_close <= ema_fast and ema_fast <= ema_slow:
        return "Bearish"
    elif latest_close > ema_slow:
        return "Bullish"
    elif latest_close < ema_slow:
        return "Bearish"
    return "Neutral"
