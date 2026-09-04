from typing import Optional, Sequence
from pydantic import BaseModel
from market_data.models import Candle
from .swings import SwingPoint


class LiquidityLevel(BaseModel):
    level_type: str         # "BSL" (Buy-Side) or "SSL" (Sell-Side)
    price: float
    origin_swing_idx: int
    origin_time: int
    is_swept: bool = False


class EqualHighLowPool(BaseModel):
    pool_type: str          # "EQH" (Equal Highs) or "EQL" (Equal Lows)
    level: float
    prices: list[float] = []
    tolerance_pct: float = 0.0
    description: str = ""


class LiquiditySweep(BaseModel):
    detected: bool = False
    sweep_type: Optional[str] = None          # BULLISH (swept SSL/EQL) or BEARISH (swept BSL/EQH)
    sweep_level: float = 0.0                 # The swing level swept
    extreme_price: float = 0.0               # The wick peak/trough
    penetration: float = 0.0                 # Absolute penetration distance
    penetration_pct: float = 0.0             # Penetration percentage
    reclaim_confirmed: bool = False          # Did price close back inside level?
    candle_index: int = -1
    candle_time: int = 0
    description: str = ""


class LiquidityEngine:
    """Detects institutional liquidity pools (BSL / SSL), Equal Highs/Lows (EQH/EQL), sweeps, grabs, and reclaims."""


    @staticmethod
    def identify_liquidity_pools(swings: list[SwingPoint]) -> list[LiquidityLevel]:
        pools = []
        for s in swings:
            l_type = "BSL" if s.point_type == "HIGH" else "SSL"
            pools.append(LiquidityLevel(
                level_type=l_type,
                price=s.price,
                origin_swing_idx=s.index,
                origin_time=s.time
            ))
        return pools

    @staticmethod
    def detect_liquidity_sweep(
        candles: Sequence[Candle],
        swings: list[SwingPoint],
        search_bars: int = 8
    ) -> LiquiditySweep:
        """
        Evaluates whether a recent candle performed a valid liquidity sweep and reclaim:
        - Bullish Sweep (Sell-Side Liquidity):
          Pierces below SSL/swing low (low < swing.price), but candle closes above swing.price
          and lower wick is significant.
        - Bearish Sweep (Buy-Side Liquidity):
          Pierces above BSL/swing high (high > swing.price), but candle closes below swing.price
          and upper wick is significant.
        """
        if len(candles) < 3 or not swings:
            return LiquiditySweep()

        n = len(candles)
        start_bar = max(0, n - search_bars)

        valid_swings = [s for s in swings if s.index < start_bar]
        if not valid_swings:
            valid_swings = [s for s in swings if s.index < n - 1]
        if not valid_swings:
            return LiquiditySweep()

        recent_lows = [s for s in valid_swings if s.point_type == "LOW"]
        recent_highs = [s for s in valid_swings if s.point_type == "HIGH"]

        for bar_idx in range(n - 1, start_bar - 1, -1):
            c = candles[bar_idx]

            # Bullish Sweep (pierces swing low, closes above)
            for s_low in reversed(recent_lows[-3:]):
                if c.low < s_low.price and c.close > s_low.price:
                    if c.lower_wick > (c.total_range * 0.20):
                        pen = s_low.price - c.low
                        pen_pct = (pen / s_low.price) * 100.0
                        return LiquiditySweep(
                            detected=True,
                            sweep_type="BULLISH",
                            sweep_level=s_low.price,
                            extreme_price=c.low,
                            penetration=round(pen, 4),
                            penetration_pct=round(pen_pct, 3),
                            reclaim_confirmed=True,
                            candle_index=bar_idx,
                            candle_time=c.time,
                            description=f"Bullish sweep of SSL {s_low.price:.2f} (wick {c.low:.2f}, closed {c.close:.2f})"
                        )

            # Bearish Sweep (pierces swing high, closes below)
            for s_high in reversed(recent_highs[-3:]):
                if c.high > s_high.price and c.close < s_high.price:
                    if c.upper_wick > (c.total_range * 0.20):
                        pen = c.high - s_high.price
                        pen_pct = (pen / s_high.price) * 100.0
                        return LiquiditySweep(
                            detected=True,
                            sweep_type="BEARISH",
                            sweep_level=s_high.price,
                            extreme_price=c.high,
                            penetration=round(pen, 4),
                            penetration_pct=round(pen_pct, 3),
                            reclaim_confirmed=True,
                            candle_index=bar_idx,
                            candle_time=c.time,
                            description=f"Bearish sweep of BSL {s_high.price:.2f} (wick {c.high:.2f}, closed {c.close:.2f})"
                        )

        # 2-candle Turtle Soup sweep detection (Bar i-1 pierces, Bar i reclaims inside level)
        for bar_idx in range(n - 1, start_bar, -1):
            c_reclaim = candles[bar_idx]
            c_sweep = candles[bar_idx - 1]

            for s_low in reversed(recent_lows[-3:]):
                if c_sweep.low < s_low.price and c_reclaim.close > s_low.price and c_reclaim.is_bullish:
                    pen = s_low.price - min(c_sweep.low, c_reclaim.low)
                    pen_pct = (pen / s_low.price) * 100.0
                    return LiquiditySweep(
                        detected=True,
                        sweep_type="BULLISH",
                        sweep_level=s_low.price,
                        extreme_price=min(c_sweep.low, c_reclaim.low),
                        penetration=round(pen, 4),
                        penetration_pct=round(pen_pct, 3),
                        reclaim_confirmed=True,
                        candle_index=bar_idx,
                        candle_time=c_reclaim.time,
                        description=f"2-Candle Bullish sweep & reclaim of SSL {s_low.price:.2f} (extreme {min(c_sweep.low, c_reclaim.low):.2f}, reclaim close {c_reclaim.close:.2f})"
                    )

            for s_high in reversed(recent_highs[-3:]):
                if c_sweep.high > s_high.price and c_reclaim.close < s_high.price and c_reclaim.is_bearish:
                    pen = max(c_sweep.high, c_reclaim.high) - s_high.price
                    pen_pct = (pen / s_high.price) * 100.0
                    return LiquiditySweep(
                        detected=True,
                        sweep_type="BEARISH",
                        sweep_level=s_high.price,
                        extreme_price=max(c_sweep.high, c_reclaim.high),
                        penetration=round(pen, 4),
                        penetration_pct=round(pen_pct, 3),
                        reclaim_confirmed=True,
                        candle_index=bar_idx,
                        candle_time=c_reclaim.time,
                        description=f"2-Candle Bearish sweep & reclaim of BSL {s_high.price:.2f} (extreme {max(c_sweep.high, c_reclaim.high):.2f}, reclaim close {c_reclaim.close:.2f})"
                    )

        return LiquiditySweep()
    @staticmethod
    def find_equal_highs_lows(
        swings: list[SwingPoint],
        tolerance_pct: float = 0.18
    ) -> list[EqualHighLowPool]:
        """
        Detects Equal Highs (EQH) and Equal Lows (EQL) within tolerance_pct (default 0.18%).
        EQH and EQL represent massive institutional retail liquidity magnets.
        """
        pools = []
        highs = [s for s in swings if s.point_type == "HIGH"]
        lows = [s for s in swings if s.point_type == "LOW"]

        # Check pairs of recent highs
        for i in range(len(highs) - 1):
            h1 = highs[i]
            for j in range(i + 1, min(i + 4, len(highs))):
                h2 = highs[j]
                diff_pct = abs(h1.price - h2.price) / max(h1.price, h2.price) * 100.0
                if diff_pct <= tolerance_pct:
                    avg_lvl = round((h1.price + h2.price) / 2.0, 2)
                    pools.append(EqualHighLowPool(
                        pool_type="EQH",
                        level=avg_lvl,
                        prices=[h1.price, h2.price],
                        tolerance_pct=round(diff_pct, 3),
                        description=f"Equal Highs (EQH) at {avg_lvl:.2f} ({h1.price:.2f}, {h2.price:.2f}, diff {diff_pct:.2f}%)"
                    ))

        # Check pairs of recent lows
        for i in range(len(lows) - 1):
            l1 = lows[i]
            for j in range(i + 1, min(i + 4, len(lows))):
                l2 = lows[j]
                diff_pct = abs(l1.price - l2.price) / max(l1.price, l2.price) * 100.0
                if diff_pct <= tolerance_pct:
                    avg_lvl = round((l1.price + l2.price) / 2.0, 2)
                    pools.append(EqualHighLowPool(
                        pool_type="EQL",
                        level=avg_lvl,
                        prices=[l1.price, l2.price],
                        tolerance_pct=round(diff_pct, 3),
                        description=f"Equal Lows (EQL) at {avg_lvl:.2f} ({l1.price:.2f}, {l2.price:.2f}, diff {diff_pct:.2f}%)"
                    ))
        return pools

    @staticmethod
    def detect_eqh_eql_sweep(
        candles: Sequence[Candle],
        eq_pools: list[EqualHighLowPool],
        search_bars: int = 8
    ) -> LiquiditySweep:
        """
        Detects if a recent candle pierced an EQH (Buy-Side) or EQL (Sell-Side) pool
        and reclaimed the level inside the range.
        """
        if len(candles) < 3 or not eq_pools:
            return LiquiditySweep()

        n = len(candles)
        start_bar = max(0, n - search_bars)

        for bar_idx in range(n - 1, start_bar - 1, -1):
            c = candles[bar_idx]
            for pool in reversed(eq_pools):
                if pool.pool_type == "EQL":
                    # Bullish reversal: swept EQL pool below, closed above
                    if c.low < pool.level and c.close > pool.level:
                        if c.lower_wick > (c.total_range * 0.20):
                            pen = pool.level - c.low
                            pen_pct = (pen / pool.level) * 100.0
                            return LiquiditySweep(
                                detected=True,
                                sweep_type="BULLISH",
                                sweep_level=pool.level,
                                extreme_price=c.low,
                                penetration=round(pen, 4),
                                penetration_pct=round(pen_pct, 3),
                                reclaim_confirmed=True,
                                candle_index=bar_idx,
                                candle_time=c.time,
                                description=f"Bullish sweep of {pool.description} (wick {c.low:.2f}, closed {c.close:.2f})"
                            )
                elif pool.pool_type == "EQH":
                    # Bearish reversal: swept EQH pool above, closed below
                    if c.high > pool.level and c.close < pool.level:
                        if c.upper_wick > (c.total_range * 0.20):
                            pen = c.high - pool.level
                            pen_pct = (pen / pool.level) * 100.0
                            return LiquiditySweep(
                                detected=True,
                                sweep_type="BEARISH",
                                sweep_level=pool.level,
                                extreme_price=c.high,
                                penetration=round(pen, 4),
                                penetration_pct=round(pen_pct, 3),
                                reclaim_confirmed=True,
                                candle_index=bar_idx,
                                candle_time=c.time,
                                description=f"Bearish sweep of {pool.description} (wick {c.high:.2f}, closed {c.close:.2f})"
                            )

        return LiquiditySweep()


# Retain standalone function alias for backward compatibility with existing tests
detect_liquidity_sweep = LiquidityEngine.detect_liquidity_sweep
