import logging
from dataclasses import dataclass
from typing import Optional, List
from market_data.models import Candle

logger = logging.getLogger("spidy.structure.trailing")


@dataclass
class TrailingResult:
    new_stop: float
    stop_moved: bool
    trail_reason: str
    locked_r: float
    achieved_r: float


class TrailingStopEngine:
    """
    Institutional Dynamic Trailing Stop Engine.
    Combines:
    1. Milestone R-Ratcheting (+1.5R -> +0.5R, +2.0R -> +1.0R, +3.0R -> +2.0R)
    2. Dynamic 1.5x ATR Structural Trail behind peak favorable excursion
    3. Swing High/Low protection
    Guarantees stop only ever moves in the direction of profit.
    """

    @staticmethod
    def evaluate_trail(
        direction: str,
        entry: float,
        original_stop: float,
        current_stop: float,
        current_price: float,
        peak_favorable_price: float,
        atr: float,
        candles_5m: Optional[List[Candle]] = None
    ) -> TrailingResult:
        risk = abs(entry - original_stop)
        if risk <= 0:
            return TrailingResult(current_stop, False, "Zero risk", 0.0, 0.0)

        # 1. Compute current achieved R from peak favorable price
        if direction == "LONG":
            fav_distance = peak_favorable_price - entry
        else:
            fav_distance = entry - peak_favorable_price
        
        achieved_r = max(0.0, fav_distance / risk)

        # 2. Apex Milestone Ratchets (3-Stage Scaler + 5R Runner Protection)
        locked_r = 0.0
        milestone_stop = current_stop

        if achieved_r >= 5.0:
            locked_r = 4.0
            milestone_stop = entry + (4.0 * risk) if direction == "LONG" else entry - (4.0 * risk)
        elif achieved_r >= 4.0:
            locked_r = 3.0
            milestone_stop = entry + (3.0 * risk) if direction == "LONG" else entry - (3.0 * risk)
        elif achieved_r >= 3.0:
            locked_r = 2.0
            milestone_stop = entry + (2.0 * risk) if direction == "LONG" else entry - (2.0 * risk)
        elif achieved_r >= 2.0:
            locked_r = 1.0
            milestone_stop = entry + (1.0 * risk) if direction == "LONG" else entry - (1.0 * risk)
        elif achieved_r >= 1.5:
            locked_r = 0.5
            milestone_stop = entry + (0.5 * risk) if direction == "LONG" else entry - (0.5 * risk)
        elif achieved_r >= 0.8:
            locked_r = 0.05  # Break-Even + Fee Buffer
            fee_buf = 0.05 * risk
            milestone_stop = (entry + fee_buf) if direction == "LONG" else (entry - fee_buf)

        # 3. ATR Dynamic Trail (active once in >= 1.5R profit)
        atr_buffer = max(1.5 * atr, entry * 0.0035)
        atr_stop = current_stop
        if achieved_r >= 1.5:
            if direction == "LONG":
                atr_stop = peak_favorable_price - atr_buffer
            else:
                atr_stop = peak_favorable_price + atr_buffer

        # 4. Recent 5M Swing Trail (lookback 3 bars)
        swing_stop = current_stop
        if candles_5m and len(candles_5m) >= 3 and achieved_r >= 1.2:
            recent_closed = [c for c in candles_5m[-4:-1]]
            if recent_closed:
                if direction == "LONG":
                    recent_low = min(c.low for c in recent_closed)
                    swing_stop = recent_low
                else:
                    recent_high = max(c.high for c in recent_closed)
                    swing_stop = recent_high

        # 5. Determine best proposed stop
        if direction == "LONG":
            # Must be above current_stop, choose best protection
            candidates = [current_stop]
            if milestone_stop > current_stop:
                candidates.append(milestone_stop)
            if atr_stop > current_stop:
                candidates.append(atr_stop)
            if swing_stop > current_stop and swing_stop < current_price:
                candidates.append(swing_stop)

            proposed = max(candidates)
            # Guard against setting stop above current price
            proposed = min(proposed, current_price - (0.2 * atr))

            if proposed > current_stop + (0.05 * risk):
                reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)" if proposed == milestone_stop else f"ATR/Structure Trail at {proposed:.2f}"
                return TrailingResult(round(proposed, 4), True, reason, locked_r, round(achieved_r, 2))
        else:
            # SHORT: Must be below current_stop
            candidates = [current_stop]
            if milestone_stop < current_stop:
                candidates.append(milestone_stop)
            if atr_stop < current_stop:
                candidates.append(atr_stop)
            if swing_stop < current_stop and swing_stop > current_price:
                candidates.append(swing_stop)

            proposed = min(candidates)
            # Guard against setting stop below current price
            proposed = max(proposed, current_price + (0.2 * atr))

            if proposed < current_stop - (0.05 * risk):
                reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)" if proposed == milestone_stop else f"ATR/Structure Trail at {proposed:.2f}"
                return TrailingResult(round(proposed, 4), True, reason, locked_r, round(achieved_r, 2))

        return TrailingResult(current_stop, False, "No trailing adjustment required", locked_r, round(achieved_r, 2))
