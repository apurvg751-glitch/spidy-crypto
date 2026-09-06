from typing import List, Optional
from pydantic import BaseModel
from market_data.models import Candle
from structure.equilibrium import DealingRange
from config.precision import round_price, format_price


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
    htf_wall_cap_applied: bool = False
    htf_wall_level: Optional[float] = None
    description: str


class TargetSnapper:
    """
    Dynamic Structural Target Snapper (Draw on Liquidity) — Multi-Timeframe.
    Anchors Take Profit 1 and 2 to physical chart structure (Swing Highs/Lows and Dealing Range Extremes).
    Additionally scans 1H/4H candles for Institutional Displacement Origins (supply/demand walls)
    and CAPS TP below those walls to prevent setting targets past institutional barriers.
    """

    @staticmethod
    def _detect_htf_walls(
        candles_1h: List[Candle],
        candles_4h: List[Candle]
    ) -> tuple[list[float], list[float]]:
        """
        Finds institutional displacement origin levels from 1H and 4H candles.
        Only massive displacement candles qualify (body >= 65%, expansion >= 1.15x avg).
        Small normal candles are completely ignored.

        Returns (supply_walls, demand_walls):
        - supply_walls: bearish displacement origins (overhead resistance for LONGs)
        - demand_walls: bullish displacement origins (floor support for SHORTs)
        """
        supply_walls: list[float] = []
        demand_walls: list[float] = []

        for candles in [candles_1h, candles_4h]:
            if not candles or len(candles) < 5:
                continue

            for i in range(max(10, 0), len(candles)):
                c = candles[i]
                c_range = c.high - c.low
                if c_range <= 0:
                    continue

                body = abs(c.close - c.open)
                body_ratio = body / c_range

                prev_start = max(0, i - 10)
                prev_ranges = [(candles[j].high - candles[j].low) for j in range(prev_start, i)]
                avg_range = (sum(prev_ranges) / len(prev_ranges)) if prev_ranges else c_range
                expansion_ratio = c_range / max(avg_range, 1e-8)

                # INSTITUTIONAL criteria: body >= 65%, expansion >= 1.15x
                if body_ratio < 0.65 or expansion_ratio < 1.15:
                    continue

                is_bearish = c.close < c.open
                if is_bearish:
                    supply_walls.append(c.open)  # Top of the bearish drop = supply
                else:
                    demand_walls.append(c.open)  # Bottom of the bullish surge = demand

        return supply_walls, demand_walls

    @classmethod
    def snap_targets(
        cls,
        direction: str,
        entry: float,
        stop_loss: float,
        candles_15m: List[Candle],
        dealing_range: Optional[DealingRange] = None,
        atr: float = 0.0,
        min_rr: float = 1.6,
        symbol: str = "ETHUSD",
        candles_1h: List[Candle] | None = None,
        candles_4h: List[Candle] | None = None
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

        # Detect HTF institutional walls
        supply_walls, demand_walls = cls._detect_htf_walls(
            candles_1h or [], candles_4h or []
        )

        htf_cap_applied = False
        htf_wall_level = None

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
                t2 = round_price(symbol, dealing_range.range_high * 0.998)
                t2_type = "DEALING_RANGE_CEILING"
            else:
                t2 = max(t1 + (risk * 0.7), entry + (risk * 2.5))
                t2_type = "MACRO_EXPANSION_2.5R"

            # 3. HTF INSTITUTIONAL SUPPLY WALL CAP (the "White Line" rule)
            # If any 1H/4H supply wall is overhead, NEVER put TP above it.
            # Cap TP at 0.998x of the wall level (just beneath the institutional barrier).
            overhead_walls = sorted([w for w in supply_walls if w > entry])
            if overhead_walls:
                nearest_wall = overhead_walls[0]  # Closest supply wall above entry
                cap_level = nearest_wall * 0.998  # Just below the wall

                if t1 > cap_level:
                    t1 = cap_level
                    t1_type = "HTF_SUPPLY_WALL_CAP"
                    htf_cap_applied = True
                    htf_wall_level = nearest_wall

                if t2 > cap_level:
                    t2 = cap_level
                    t2_type = "HTF_SUPPLY_WALL_CAP"
                    htf_cap_applied = True
                    htf_wall_level = nearest_wall

            rr_1 = round(abs(t1 - entry) / risk, 2)
            rr_2 = round(abs(t2 - entry) / risk, 2)
            has_clearance = (rr_1 >= min_rr and abs(t1 - entry) >= (entry * 0.0050))

            cap_note = f" | ⚠️ HTF Supply Wall Cap @ {format_price(symbol, htf_wall_level)}" if htf_cap_applied else ""
            desc = f"TP1 snapped to {t1_type} (${format_price(symbol, t1)} | 1:{rr_1}R) | TP2 at {t2_type} (${format_price(symbol, t2)} | 1:{rr_2}R){cap_note}"

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
                t2 = round_price(symbol, dealing_range.range_low * 1.002)
                t2_type = "DEALING_RANGE_FLOOR"
            else:
                t2 = min(t1 - (risk * 0.7), entry - (risk * 2.5))
                t2_type = "MACRO_EXPANSION_2.5R"

            # 3. HTF INSTITUTIONAL DEMAND WALL CAP (the "White Line" rule for SHORTs)
            # If any 1H/4H demand wall is below, NEVER put TP below it.
            # Cap TP at 1.002x of the wall level (just above the institutional barrier).
            below_walls = sorted([w for w in demand_walls if w < entry], reverse=True)
            if below_walls:
                nearest_wall = below_walls[0]  # Closest demand wall below entry
                cap_level = nearest_wall * 1.002  # Just above the wall

                if t1 < cap_level:
                    t1 = cap_level
                    t1_type = "HTF_DEMAND_WALL_CAP"
                    htf_cap_applied = True
                    htf_wall_level = nearest_wall

                if t2 < cap_level:
                    t2 = cap_level
                    t2_type = "HTF_DEMAND_WALL_CAP"
                    htf_cap_applied = True
                    htf_wall_level = nearest_wall

            rr_1 = round(abs(entry - t1) / risk, 2)
            rr_2 = round(abs(entry - t2) / risk, 2)
            has_clearance = (rr_1 >= min_rr and abs(entry - t1) >= (entry * 0.0050))

            cap_note = f" | ⚠️ HTF Demand Wall Cap @ {format_price(symbol, htf_wall_level)}" if htf_cap_applied else ""
            desc = f"TP1 snapped to {t1_type} (${format_price(symbol, t1)} | 1:{rr_1}R) | TP2 at {t2_type} (${format_price(symbol, t2)} | 1:{rr_2}R){cap_note}"

        return SnappedTargets(
            entry=round_price(symbol, entry),
            stop_loss=round_price(symbol, stop_loss),
            target_1=round_price(symbol, t1),
            target_2=round_price(symbol, t2),
            rr_1=rr_1,
            rr_2=rr_2,
            target_1_type=t1_type,
            target_2_type=t2_type,
            has_minimum_clearance=has_clearance,
            htf_wall_cap_applied=htf_cap_applied,
            htf_wall_level=htf_wall_level,
            description=desc
        )
