import logging
from dataclasses import dataclass
from typing import Optional, List
from market_data.models import Candle

logger = logging.getLogger("spidy.structure.trailing")


from config.precision import round_price


@dataclass
class TrailingResult:
    new_stop: float
    stop_moved: bool
    trail_reason: str
    locked_r: float
    achieved_r: float
    is_breakeven: bool = False


class TrailingStopEngine:
    """
    Institutional Dynamic Trailing Stop Engine.
    Combines:
    1. Milestone R-Ratcheting (+1.5R -> +0.5R, +2.0R -> +1.0R, +3.0R -> +2.0R)
    2. Dynamic 1.5x ATR Structural Trail behind peak favorable excursion
    3. Swing High/Low protection
    Guarantees stop only ever moves in the direction of profit without premature stop-outs.
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
        candles_5m: Optional[List[Candle]] = None,
        candles_15m: Optional[List[Candle]] = None,
        symbol: str = "ETHUSD"
    ) -> TrailingResult:
        risk = abs(entry - original_stop)
        if risk <= 0:
            return TrailingResult(current_stop, False, "Zero risk", 0.0, 0.0, False)

        # 1. Compute current achieved R from peak favorable price
        if direction == "LONG":
            fav_distance = peak_favorable_price - entry
        else:
            fav_distance = entry - peak_favorable_price
        
        achieved_r = max(0.0, fav_distance / risk)

        # FULL BREATHING ROOM GUARD (INSTITUTIONAL RULE):
        # When trade is developing (achieved_r < 0.8R), Stop Loss is STRICTLY LOCKED at original invalidation!
        # NO structural trailing, wick ratchets, or premature tightening are permitted below 0.8R.
        if achieved_r < 0.8:
            return TrailingResult(
                new_stop=current_stop,
                stop_moved=False,
                trail_reason=f"Breathing Room Active (< 0.8R): Stop locked at invalidation (Peak: +{achieved_r:.2f}R)",
                locked_r=0.0,
                achieved_r=round(achieved_r, 2),
                is_breakeven=False
            )

        # 2. Apex Milestone Ratchets (Cash-First & Runner Protection)
        locked_r = 0.0
        milestone_stop = current_stop
        is_be = False

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
            fee_buf = max(0.05 * risk, entry * 0.0008)  # Guarantees >= 0.08% profit to cover Delta fee + spread
            milestone_stop = (entry + fee_buf) if direction == "LONG" else (entry - fee_buf)
            is_be = True

        # 3. ATR Dynamic Trail (active once in >= 1.5R profit for runners)
        atr_buffer = max(1.5 * atr, entry * 0.0035)
        atr_stop = current_stop
        if achieved_r >= 1.5:
            if direction == "LONG":
                atr_stop = peak_favorable_price - atr_buffer
            else:
                atr_stop = peak_favorable_price + atr_buffer

        # 4. Structural Swings (Only for Runners >= 1.5R, using confirmed 15M or deep 5M structure)
        # Banned for developing trades (< 1.5R) to prevent stop-outs on short-term liquidity sweeps.
        breathing_room = max(1.0 * atr, entry * 0.0050)
        structural_stop = current_stop
        structural_reason = ""

        candles_for_swings = candles_15m if (candles_15m and len(candles_15m) >= 5) else (candles_5m if (candles_5m and len(candles_5m) >= 6) else None)
        if achieved_r >= 1.5 and candles_for_swings:
            from structure.swings import find_swings
            swings = find_swings(candles_for_swings, lookback=2, is_major=False)

            if direction == "LONG":
                # Confirmed swing lows above current stop and below current price
                valid_lows = [
                    s for s in swings
                    if s.point_type == "LOW" and s.price > current_stop and s.price <= (current_price - breathing_room)
                ]
                if valid_lows:
                    hl_swings = [s for s in valid_lows if s.structure_label == "HL"]
                    best_low = hl_swings[-1] if hl_swings else valid_lows[-1]
                    cand_stop = best_low.price - (0.05 * atr)
                    if cand_stop > current_stop:
                        structural_stop = cand_stop
                        structural_reason = f"Structural Higher Low (HL) at {best_low.price:.2f}"
            else:
                # Confirmed swing highs below current stop and above current price
                valid_highs = [
                    s for s in swings
                    if s.point_type == "HIGH" and s.price < current_stop and s.price >= (current_price + breathing_room)
                ]
                if valid_highs:
                    lh_swings = [s for s in valid_highs if s.structure_label == "LH"]
                    best_high = lh_swings[-1] if lh_swings else valid_highs[-1]
                    cand_stop = best_high.price + (0.05 * atr)
                    if cand_stop < current_stop:
                        structural_stop = cand_stop
                        structural_reason = f"Structural Lower High (LH) at {best_high.price:.2f}"

        # 5. Determine best proposed stop
        if direction == "LONG":
            if structural_stop > current_stop and structural_reason:
                best_stop = structural_stop
                reason = structural_reason
                if milestone_stop > structural_stop:
                    best_stop = milestone_stop
                    reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            elif atr_stop > current_stop and achieved_r >= 1.5:
                best_stop = atr_stop
                reason = f"ATR Dynamic Trail at {atr_stop:.2f}"
                if milestone_stop > atr_stop:
                    best_stop = milestone_stop
                    reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            elif milestone_stop > current_stop:
                best_stop = milestone_stop
                reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            else:
                best_stop = current_stop
                reason = "No change"

            if best_stop == milestone_stop:
                max_allowed_stop = current_price - (entry * 0.0005)
            else:
                max_allowed_stop = current_price - breathing_room
            if best_stop > max_allowed_stop:
                best_stop = max_allowed_stop

            if best_stop > current_stop + (0.05 * risk):
                return TrailingResult(round_price(symbol, best_stop), True, reason, locked_r, round(achieved_r, 2), is_be)
        else:
            if structural_stop < current_stop and structural_reason:
                best_stop = structural_stop
                reason = structural_reason
                if milestone_stop < structural_stop:
                    best_stop = milestone_stop
                    reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            elif atr_stop < current_stop and achieved_r >= 1.5:
                best_stop = atr_stop
                reason = f"ATR Dynamic Trail at {atr_stop:.2f}"
                if milestone_stop < atr_stop:
                    best_stop = milestone_stop
                    reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            elif milestone_stop < current_stop:
                best_stop = milestone_stop
                reason = f"Ratchet: Locked {locked_r:.1f}R (Peak: +{achieved_r:.2f}R)"
            else:
                best_stop = current_stop
                reason = "No change"

            if best_stop == milestone_stop:
                min_allowed_stop = current_price + (entry * 0.0005)
            else:
                min_allowed_stop = current_price + breathing_room
            if best_stop < min_allowed_stop:
                best_stop = min_allowed_stop

            if best_stop < current_stop - (0.05 * risk):
                return TrailingResult(round_price(symbol, best_stop), True, reason, locked_r, round(achieved_r, 2), is_be)

        return TrailingResult(current_stop, False, "No trailing adjustment required", locked_r, round(achieved_r, 2), is_be)
