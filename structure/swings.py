from typing import Sequence, Literal, Optional
from pydantic import BaseModel
from market_data.models import Candle


class SwingPoint(BaseModel):
    index: int
    time: int
    price: float
    point_type: Literal["HIGH", "LOW"]
    structure_label: Optional[Literal["HH", "HL", "LH", "LL"]] = None
    is_major: bool = False


def find_swings(
    candles: Sequence[Candle],
    lookback: int = 3,
    is_major: bool = False
) -> list[SwingPoint]:
    """
    Identifies fractal swing highs and swing lows using a symmetric lookback window.
    Supports distinguishing Major structure (e.g. lookback=5) from Internal structure (e.g. lookback=2-3).
    """
    if len(candles) < (lookback * 2 + 1):
        return []

    swings: list[SwingPoint] = []
    n = len(candles)

    for i in range(lookback, n - lookback):
        current = candles[i]

        # Check Swing High
        is_high = True
        for j in range(i - lookback, i):
            if candles[j].high >= current.high:
                is_high = False
                break
        if is_high:
            for j in range(i + 1, i + lookback + 1):
                if candles[j].high > current.high:
                    is_high = False
                    break

        if is_high:
            swings.append(SwingPoint(
                index=i,
                time=current.time,
                price=current.high,
                point_type="HIGH",
                is_major=is_major
            ))
            continue

        # Check Swing Low
        is_low = True
        for j in range(i - lookback, i):
            if candles[j].low <= current.low:
                is_low = False
                break
        if is_low:
            for j in range(i + 1, i + lookback + 1):
                if candles[j].low < current.low:
                    is_low = False
                    break

        if is_low:
            swings.append(SwingPoint(
                index=i,
                time=current.time,
                price=current.low,
                point_type="LOW",
                is_major=is_major
            ))

    # Classify swings into HH, HL, LH, LL
    return classify_swings(swings)


def classify_swings(swings: list[SwingPoint]) -> list[SwingPoint]:
    """Labels swing points as HH, HL, LH, or LL relative to preceding swings."""
    highs = [s for s in swings if s.point_type == "HIGH"]
    lows = [s for s in swings if s.point_type == "LOW"]

    for idx, s in enumerate(highs):
        if idx == 0:
            continue
        prev = highs[idx - 1]
        s.structure_label = "HH" if s.price > prev.price else "LH"

    for idx, s in enumerate(lows):
        if idx == 0:
            continue
        prev = lows[idx - 1]
        s.structure_label = "HL" if s.price > prev.price else "LL"

    return swings
