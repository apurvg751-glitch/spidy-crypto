from typing import List, Optional
from pydantic import BaseModel
from market_data.models import Candle
from structure.equilibrium import DealingRange


class SnappedTargets(BaseModel):
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    rr_1: float
    rr_2: float
    target_1_type: str         # "PHYSICAL_SWING_HIGH", "PHYSICAL_SWING_LOW", "DEALING_RANGE_EXTREME"
    target_2_type: str
    has_minimum_clearance: bool
    description: str


class TargetSnapper:
    """
    Dynamic Structural Target Snapper (Draw on Liquidity).
    Anchors Take Profit 1 and 2 to physical chart structure (Swing Highs/Lows and Dealing Range Extremes),
    eliminating arbitrary fantasy multiplier targets.
    """

    @classmethod
    def snap_targets(
        cls,
        direction: str,
        entry: float,
        stop_loss: float,
        candles_15m: List[Candle],
        dealing_range: Optional[DealingRange] = None,
        atr: float = 0.0,
        min_rr: float = 1.6
    ) -> SnappedTargets:
        risk = abs(entry - stop_loss)
        min_risk = max(entry * 0.0035, atr * 0.60) if atr > 0 else (entry * 0.0035)
        if risk < min_risk:
            risk = min_risk
            stop_loss = (entry - risk) if direction.upper() == "LONG" else (entry + risk)

        # Minimum required distance for TP1: at least 1.6R and at least 0.50% / 1.2x ATR
        min_t1_dist = max(risk * min_rr, entry * 0.0050, (atr * 1.2) if atr > 0 else (entry * 0.0050))

        highs = [c.high for c in candles_15m[-24:]] if candles_15m else [entry * 1.02]
        lows = [c.low for c in candles_15m[-24:]] if candles_15m else [entry * 0.98]

        if direction.upper() == "LONG":
            # 1. Look for physical swing highs at least min_t1_dist above entry
            potential_t1 = [h for h in highs if h >= entry + min_t1_dist]
            if potential_t1:
                t1 = min(potential_t1)  # Nearest physical swing ceiling with adequate room
                t1_type = "PHYSICAL_SWING_HIGH"
            else:
                t1 = entry + max(risk * 1.8, min_t1_dist)
                t1_type = "DYNAMIC_EXPANSION_1.8R"

            # 2. Look for Dealing Range Extreme for T2
            if dealing_range and dealing_range.range_high > t1 + (risk * 0.5):
                t2 = round(dealing_range.range_high * 0.998, 2)
                t2_type = "DEALING_RANGE_CEILING"
            else:
                t2 = max(t1 + (risk * 0.7), entry + (risk * 2.5))
                t2_type = "MACRO_EXPANSION_2.5R"

            rr_1 = round(abs(t1 - entry) / risk, 2)
            rr_2 = round(abs(t2 - entry) / risk, 2)
            has_clearance = (rr_1 >= min_rr and abs(t1 - entry) >= (entry * 0.0050))

            desc = f"TP1 snapped to {t1_type} (${t1:,.2f} | 1:{rr_1}R) | TP2 at {t2_type} (${t2:,.2f} | 1:{rr_2}R)"

        else:  # SHORT
            # 1. Look for physical swing lows at least min_t1_dist below entry
            potential_t1 = [l for l in lows if l <= entry - min_t1_dist]
            if potential_t1:
                t1 = max(potential_t1)  # Nearest physical swing floor with adequate room
                t1_type = "PHYSICAL_SWING_LOW"
            else:
                t1 = entry - max(risk * 1.8, min_t1_dist)
                t1_type = "DYNAMIC_EXPANSION_1.8R"

            # 2. Look for Dealing Range Extreme for T2
            if dealing_range and dealing_range.range_low < t1 - (risk * 0.5):
                t2 = round(dealing_range.range_low * 1.002, 2)
                t2_type = "DEALING_RANGE_FLOOR"
            else:
                t2 = min(t1 - (risk * 0.7), entry - (risk * 2.5))
                t2_type = "MACRO_EXPANSION_2.5R"

            rr_1 = round(abs(entry - t1) / risk, 2)
            rr_2 = round(abs(entry - t2) / risk, 2)
            has_clearance = (rr_1 >= min_rr and abs(entry - t1) >= (entry * 0.0050))

            desc = f"TP1 snapped to {t1_type} (${t1:,.2f} | 1:{rr_1}R) | TP2 at {t2_type} (${t2:,.2f} | 1:{rr_2}R)"

        return SnappedTargets(
            entry=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            target_1=round(t1, 2),
            target_2=round(t2, 2),
            rr_1=rr_1,
            rr_2=rr_2,
            target_1_type=t1_type,
            target_2_type=t2_type,
            has_minimum_clearance=has_clearance,
            description=desc
        )
