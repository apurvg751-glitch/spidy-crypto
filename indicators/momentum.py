from typing import Sequence
from market_data.models import Candle


def calculate_rsi(prices: Sequence[float], period: int = 14) -> float:
    """Calculates Relative Strength Index (RSI)."""
    if len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, period + 1):
        delta = prices[i] - prices[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = abs(delta) if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_roc(prices: Sequence[float], period: int = 9) -> float:
    """Calculates Rate of Change (ROC) percentage."""
    if len(prices) < period + 1 or prices[-period - 1] == 0:
        return 0.0
    return ((prices[-1] - prices[-period - 1]) / prices[-period - 1]) * 100.0


def is_momentum_aligned(candles: Sequence[Candle], direction: str) -> bool:
    """
    Evaluates whether momentum supports the trade direction:
    - LONG: RSI > 45 and rising OR ROC > 0
    - SHORT: RSI < 55 and falling OR ROC < 0
    """
    if len(candles) < 15:
        return True

    closes = [c.close for c in candles]
    rsi_now = calculate_rsi(closes)
    rsi_prev = calculate_rsi(closes[:-1])
    roc = calculate_roc(closes)

    if direction == "LONG":
        return (rsi_now >= 45 and rsi_now >= rsi_prev) or roc > 0
    elif direction == "SHORT":
        return (rsi_now <= 55 and rsi_now <= rsi_prev) or roc < 0
    return False
