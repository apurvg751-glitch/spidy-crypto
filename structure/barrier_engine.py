from typing import Optional
from pydantic import BaseModel
from market_data.models import Candle
from structure.swings import find_swings, SwingPoint
from structure.equilibrium import DealingRange


class BarrierValidationResult(BaseModel):
    is_valid: bool
    nearest_ceiling: Optional[float] = None
    nearest_floor: Optional[float] = None
    distance_to_ceiling: Optional[float] = None
    distance_to_floor: Optional[float] = None
    distance_to_ceiling_pct: Optional[float] = None
    distance_to_floor_pct: Optional[float] = None
    reason: str


class BarrierEngine:
    """
    Structural Barrier Engine:
    1. Identifies major 15M/1H resistance ceilings (double-tops, equal highs, major swing highs)
       and support floors (double-bottoms, equal lows, major swing lows).
    2. Enforces the 'Room to Run' rule:
       - LONGs require clearance of at least 0.45% (or 1.5x ATR) below major resistance.
       - SHORTs require clearance of at least 0.45% (or 1.5x ATR) above major support.
    3. Enforces Whole Structure Range Hard Bans:
       - Top 25% (Roof Zone): All LONGs strictly blocked.
       - Bottom 25% (Floor Zone): All SHORTs strictly blocked.
    """

    @staticmethod
    def find_major_barriers(candles: list[Candle]) -> tuple[list[float], list[float]]:
        """Finds prominent resistance ceilings and support floors from swing points."""
        if len(candles) < 15:
            return [], []

        swings = find_swings(candles, lookback=4)
        ceilings = sorted([s.price for s in swings if s.point_type == "HIGH"], reverse=True)
        floors = sorted([s.price for s in swings if s.point_type == "LOW"])
        return ceilings, floors

    @classmethod
    def validate_room_to_run(
        cls,
        direction: str,
        current_price: float,
        candles_15m: list[Candle],
        atr: float = 0.0,
        dealing_range: Optional[DealingRange] = None
    ) -> BarrierValidationResult:
        """
        Validates whether current price has adequate clearance (room to run)
        without running directly into a brick-wall ceiling or support floor.
        """
        if not candles_15m or len(candles_15m) < 10 or current_price <= 0:
            return BarrierValidationResult(
                is_valid=True,
                reason="Insufficient structural data; neutral clearance"
            )

        # 1. Whole Structure Range Check (Top 25% vs Bottom 25%)
        if dealing_range and dealing_range.range_span > 0:
            pos_pct = (current_price - dealing_range.range_low) / dealing_range.range_span
            if direction.upper() == "LONG" and pos_pct >= 0.75:
                return BarrierValidationResult(
                    is_valid=False,
                    reason=f"LONG Blocked: Price at {pos_pct*100:.1f}% of Dealing Range is in ROOF ZONE (Top 25% Resistance)"
                )
            if direction.upper() == "SHORT" and pos_pct <= 0.25:
                return BarrierValidationResult(
                    is_valid=False,
                    reason=f"SHORT Blocked: Price at {pos_pct*100:.1f}% of Dealing Range is in FLOOR ZONE (Bottom 25% Support)"
                )

        ceilings, floors = cls.find_major_barriers(candles_15m)

        # 2. Minimum Barrier Buffer (0.45% of price or 1.5x ATR)
        min_buffer_pts = max(current_price * 0.0045, atr * 1.5 if atr > 0 else current_price * 0.0045)

        if direction.upper() == "LONG":
            # Find closest overhead ceiling above current price
            overhead = [c for c in ceilings if c > current_price]
            nearest_ceiling = min(overhead) if overhead else None

            if nearest_ceiling is not None:
                dist = nearest_ceiling - current_price
                dist_pct = (dist / current_price) * 100.0

                if dist < min_buffer_pts:
                    return BarrierValidationResult(
                        is_valid=False,
                        nearest_ceiling=nearest_ceiling,
                        distance_to_ceiling=dist,
                        distance_to_ceiling_pct=dist_pct,
                        reason=f"LONG Blocked: Price {current_price:.2f} is within {dist_pct:.2f}% of Major Resistance Ceiling at {nearest_ceiling:.2f} (No Room to Run)"
                    )

                return BarrierValidationResult(
                    is_valid=True,
                    nearest_ceiling=nearest_ceiling,
                    distance_to_ceiling=dist,
                    distance_to_ceiling_pct=dist_pct,
                    reason=f"Adequate clearance to overhead ceiling ({dist_pct:.2f}% room)"
                )

            return BarrierValidationResult(
                is_valid=True,
                reason="Open blue sky above (No major overhead resistance found)"
            )

        elif direction.upper() == "SHORT":
            # Find closest support floor below current price
            underneath = [f for f in floors if f < current_price]
            nearest_floor = max(underneath) if underneath else None

            if nearest_floor is not None:
                dist = current_price - nearest_floor
                dist_pct = (dist / current_price) * 100.0

                if dist < min_buffer_pts:
                    return BarrierValidationResult(
                        is_valid=False,
                        nearest_floor=nearest_floor,
                        distance_to_floor=dist,
                        distance_to_floor_pct=dist_pct,
                        reason=f"SHORT Blocked: Price {current_price:.2f} is within {dist_pct:.2f}% of Major Support Floor at {nearest_floor:.2f} (No Room to Run)"
                    )

                return BarrierValidationResult(
                    is_valid=True,
                    nearest_floor=nearest_floor,
                    distance_to_floor=dist,
                    distance_to_floor_pct=dist_pct,
                    reason=f"Adequate clearance to support floor ({dist_pct:.2f}% room)"
                )

            return BarrierValidationResult(
                is_valid=True,
                reason="Open air below (No major support floor found)"
            )

        return BarrierValidationResult(is_valid=True, reason="Direction neutral")
