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
    htf_institutional_walls: list[float] = []
    reason: str

    @property
    def has_room(self) -> bool:
        """Alias for is_valid — used by setup_detector."""
        return self.is_valid


class BarrierEngine:
    """
    Structural Barrier Engine (Multi-Timeframe):
    1. Identifies major 15M swing ceilings/floors (double-tops, equal highs, major swing highs).
    2. Scans 1H and 4H candles for INSTITUTIONAL DISPLACEMENT ORIGINS —
       massive momentum candles (body > 65%, expansion > 1.15x avg range) that created
       supply/demand walls. Small red/green candles are IGNORED (not institutional).
    3. Enforces the 'Room to Run' rule with HTF walls included.
    4. Enforces Whole Structure Range Hard Bans (Top 25% / Bottom 25%).
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

    @staticmethod
    def detect_htf_institutional_walls(
        candles_1h: list[Candle],
        candles_4h: list[Candle]
    ) -> tuple[list[float], list[float]]:
        """
        Scans 1H and 4H candles for Institutional Displacement Origins.
        These are massive momentum candles where smart money entered/exited,
        creating supply walls (overhead resistance) and demand walls (floor support).

        Criteria for an Institutional Displacement Origin:
        - Body ratio >= 0.65 (body is at least 65% of total candle range — decisive, not a wick candle)
        - Expansion ratio >= 1.15 (candle range is at least 1.15x the average of previous 10 candles)

        Small normal candles are COMPLETELY IGNORED — only genuine institutional walls are tagged.

        Returns (supply_walls, demand_walls):
        - supply_walls: prices where bearish institutional displacement originated (overhead resistance)
        - demand_walls: prices where bullish institutional displacement originated (floor support)
        """
        supply_walls: list[float] = []  # Overhead resistance for LONGs
        demand_walls: list[float] = []  # Floor support for SHORTs

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

                # Calculate average range of previous 10 candles for expansion check
                prev_start = max(0, i - 10)
                prev_ranges = [(candles[j].high - candles[j].low) for j in range(prev_start, i)]
                avg_range = (sum(prev_ranges) / len(prev_ranges)) if prev_ranges else c_range
                expansion_ratio = c_range / max(avg_range, 1e-8)

                # INSTITUTIONAL DISPLACEMENT CRITERIA (strict — ignores normal small candles):
                # 1. Body must be at least 65% of total range (decisive institutional move)
                # 2. Range must be at least 1.15x larger than recent average (expansion)
                is_institutional = (body_ratio >= 0.65) and (expansion_ratio >= 1.15)

                if not is_institutional:
                    continue

                is_bearish = c.close < c.open

                if is_bearish:
                    # Bearish displacement origin = SUPPLY WALL at the open (top of the drop)
                    # This is where institutions sold — price will struggle to break above
                    supply_walls.append(c.open)
                else:
                    # Bullish displacement origin = DEMAND WALL at the open (bottom of the surge)
                    # This is where institutions bought — price will struggle to break below
                    demand_walls.append(c.open)

        return supply_walls, demand_walls

    @classmethod
    def validate_room_to_run(
        cls,
        direction: str,
        current_price: float,
        candles_15m: list[Candle],
        atr: float = 0.0,
        dealing_range: Optional[DealingRange] = None,
        candles_1h: list[Candle] | None = None,
        candles_4h: list[Candle] | None = None
    ) -> BarrierValidationResult:
        """
        Validates whether current price has adequate clearance (room to run)
        without running directly into a brick-wall ceiling or support floor.
        Now includes 1H/4H institutional displacement origins as HTF barriers.
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

        # 2. Get 15M swing barriers
        ceilings, floors = cls.find_major_barriers(candles_15m)

        # 3. Merge HTF Institutional Displacement Walls
        htf_walls_found: list[float] = []
        supply_walls, demand_walls = cls.detect_htf_institutional_walls(
            candles_1h or [], candles_4h or []
        )

        if direction.upper() == "LONG":
            # Add HTF supply walls as overhead ceilings for LONGs
            for wall in supply_walls:
                if wall > current_price:
                    ceilings.append(wall)
                    htf_walls_found.append(wall)
        elif direction.upper() == "SHORT":
            # Add HTF demand walls as floor support for SHORTs
            for wall in demand_walls:
                if wall < current_price:
                    floors.append(wall)
                    htf_walls_found.append(wall)

        # Re-sort after merging
        ceilings = sorted(ceilings, reverse=True)
        floors = sorted(floors)

        # 4. Minimum Barrier Buffer (0.45% of price or 1.5x ATR)
        min_buffer_pts = max(current_price * 0.0045, atr * 1.5 if atr > 0 else current_price * 0.0045)

        if direction.upper() == "LONG":
            # Find closest overhead ceiling above current price
            overhead = [c for c in ceilings if c > current_price]
            nearest_ceiling = min(overhead) if overhead else None

            if nearest_ceiling is not None:
                dist = nearest_ceiling - current_price
                dist_pct = (dist / current_price) * 100.0
                is_htf = nearest_ceiling in htf_walls_found

                if dist < min_buffer_pts:
                    wall_label = "HTF Institutional Supply Wall" if is_htf else "Major Resistance Ceiling"
                    return BarrierValidationResult(
                        is_valid=False,
                        nearest_ceiling=nearest_ceiling,
                        distance_to_ceiling=dist,
                        distance_to_ceiling_pct=dist_pct,
                        htf_institutional_walls=htf_walls_found,
                        reason=f"LONG Blocked: Price {current_price:.2f} is within {dist_pct:.2f}% of {wall_label} at {nearest_ceiling:.2f} (No Room to Run)"
                    )

                return BarrierValidationResult(
                    is_valid=True,
                    nearest_ceiling=nearest_ceiling,
                    distance_to_ceiling=dist,
                    distance_to_ceiling_pct=dist_pct,
                    htf_institutional_walls=htf_walls_found,
                    reason=f"Adequate clearance to overhead {'HTF institutional wall' if is_htf else 'ceiling'} ({dist_pct:.2f}% room)"
                )

            return BarrierValidationResult(
                is_valid=True,
                htf_institutional_walls=htf_walls_found,
                reason="Open blue sky above (No major overhead resistance found)"
            )

        elif direction.upper() == "SHORT":
            # Find closest support floor below current price
            underneath = [f for f in floors if f < current_price]
            nearest_floor = max(underneath) if underneath else None

            if nearest_floor is not None:
                dist = current_price - nearest_floor
                dist_pct = (dist / current_price) * 100.0
                is_htf = nearest_floor in htf_walls_found

                if dist < min_buffer_pts:
                    wall_label = "HTF Institutional Demand Wall" if is_htf else "Major Support Floor"
                    return BarrierValidationResult(
                        is_valid=False,
                        nearest_floor=nearest_floor,
                        distance_to_floor=dist,
                        distance_to_floor_pct=dist_pct,
                        htf_institutional_walls=htf_walls_found,
                        reason=f"SHORT Blocked: Price {current_price:.2f} is within {dist_pct:.2f}% of {wall_label} at {nearest_floor:.2f} (No Room to Run)"
                    )

                return BarrierValidationResult(
                    is_valid=True,
                    nearest_floor=nearest_floor,
                    distance_to_floor=dist,
                    distance_to_floor_pct=dist_pct,
                    htf_institutional_walls=htf_walls_found,
                    reason=f"Adequate clearance to {'HTF institutional wall' if is_htf else 'support floor'} ({dist_pct:.2f}% room)"
                )

            return BarrierValidationResult(
                is_valid=True,
                htf_institutional_walls=htf_walls_found,
                reason="Open air below (No major support floor found)"
            )

        return BarrierValidationResult(is_valid=True, reason="Direction neutral")
