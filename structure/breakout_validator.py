from typing import Optional, Literal
from pydantic import BaseModel, Field
from market_data.models import Candle
from indicators.volume import calculate_rvol


class BreakoutValidationResult(BaseModel):
    is_real_breakout: bool
    is_fake_breakout: bool
    trap_type: Optional[Literal["BULL_TRAP", "BEAR_TRAP"]] = None
    displacement_ratio: float
    rvol: float
    recommended_action: Literal["ENTER_BREAKOUT", "REVERSE_TRAP", "REJECT"]
    reasons: list[str] = Field(default_factory=list)


class BreakoutValidator:
    """
    Quantitative Fake Breakout vs. Real Breakout Engine.
    Detects institutional displacement vs. retail liquidity traps.
    """

    @staticmethod
    def validate_breakout(
        candles: list[Candle],
        breakout_level: float,
        direction: Literal["LONG", "SHORT"],
        atr: float,
        rvol_lookback: int = 20
    ) -> BreakoutValidationResult:
        if len(candles) < 3:
            return BreakoutValidationResult(
                is_real_breakout=False,
                is_fake_breakout=False,
                displacement_ratio=0.0,
                rvol=1.0,
                recommended_action="REJECT",
                reasons=["Insufficient candle history for breakout validation"]
            )

        c = candles[-1]
        candle_range = abs(c.high - c.low)
        body_size = abs(c.close - c.open)
        disp_ratio = round(body_size / max(candle_range, 1e-5), 2)
        rvol = round(calculate_rvol(candles, rvol_lookback), 2)
        reasons = []

        if direction == "LONG":
            upper_wick = c.high - max(c.open, c.close)
            wick_ratio = upper_wick / max(candle_range, 1e-5)
            closed_above = c.close > breakout_level

            # 1. Fake Breakout / Bull Trap Signature:
            # Price breached above level with high/wick, but closed back below OR left a dominant upper wick (>50%)
            is_wick_rejection = (wick_ratio >= 0.50 and disp_ratio < 0.50)
            is_failed_acceptance = (c.high > breakout_level and c.close <= breakout_level)

            if is_wick_rejection or is_failed_acceptance:
                reasons.append(f"Bull Trap Detected: Upper wick {wick_ratio:.0%} exceeded body {disp_ratio:.0%}")
                if is_failed_acceptance:
                    reasons.append(f"Failed Acceptance: Price wicked above {breakout_level:.2f} but closed below ({c.close:.2f})")
                return BreakoutValidationResult(
                    is_real_breakout=False,
                    is_fake_breakout=True,
                    trap_type="BULL_TRAP",
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="REVERSE_TRAP",
                    reasons=reasons
                )

            # 2. Real Breakout Signature:
            # Strong body (>= 60%), closed above breakout level by at least 0.1x ATR, and volume surge (RVOL >= 1.25)
            clean_expansion = closed_above and (disp_ratio >= 0.60)
            volume_surge = rvol >= 1.25

            if clean_expansion and volume_surge:
                reasons.append(f"Real Bullish Breakout: Strong displacement body ({disp_ratio:.0%}) with RVOL surge {rvol:.2f}x")
                return BreakoutValidationResult(
                    is_real_breakout=True,
                    is_fake_breakout=False,
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="ENTER_BREAKOUT",
                    reasons=reasons
                )
            else:
                if not volume_surge:
                    reasons.append(f"Low Volume Breakout: RVOL {rvol:.2f}x is below institutional threshold (1.25x)")
                if not clean_expansion:
                    reasons.append(f"Weak Displacement: Candle body {disp_ratio:.0%} lacks institutional conviction (<60%)")
                return BreakoutValidationResult(
                    is_real_breakout=False,
                    is_fake_breakout=False,
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="REJECT",
                    reasons=reasons
                )

        else:  # SHORT
            lower_wick = min(c.open, c.close) - c.low
            wick_ratio = lower_wick / max(candle_range, 1e-5)
            closed_below = c.close < breakout_level

            # 1. Fake Breakout / Bear Trap Signature:
            is_wick_rejection = (wick_ratio >= 0.50 and disp_ratio < 0.50)
            is_failed_acceptance = (c.low < breakout_level and c.close >= breakout_level)

            if is_wick_rejection or is_failed_acceptance:
                reasons.append(f"Bear Trap Detected: Lower wick {wick_ratio:.0%} exceeded body {disp_ratio:.0%}")
                if is_failed_acceptance:
                    reasons.append(f"Failed Acceptance: Price wicked below {breakout_level:.2f} but closed above ({c.close:.2f})")
                return BreakoutValidationResult(
                    is_real_breakout=False,
                    is_fake_breakout=True,
                    trap_type="BEAR_TRAP",
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="REVERSE_TRAP",
                    reasons=reasons
                )

            # 2. Real Breakout Signature:
            clean_expansion = closed_below and (disp_ratio >= 0.60)
            volume_surge = rvol >= 1.25

            if clean_expansion and volume_surge:
                reasons.append(f"Real Bearish Breakout: Strong displacement body ({disp_ratio:.0%}) with RVOL surge {rvol:.2f}x")
                return BreakoutValidationResult(
                    is_real_breakout=True,
                    is_fake_breakout=False,
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="ENTER_BREAKOUT",
                    reasons=reasons
                )
            else:
                if not volume_surge:
                    reasons.append(f"Low Volume Breakdown: RVOL {rvol:.2f}x is below institutional threshold (1.25x)")
                if not clean_expansion:
                    reasons.append(f"Weak Displacement: Candle body {disp_ratio:.0%} lacks institutional conviction (<60%)")
                return BreakoutValidationResult(
                    is_real_breakout=False,
                    is_fake_breakout=False,
                    displacement_ratio=disp_ratio,
                    rvol=rvol,
                    recommended_action="REJECT",
                    reasons=reasons
                )
