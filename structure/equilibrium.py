from typing import Optional
from pydantic import BaseModel
from market_data.models import Candle


class DealingRange(BaseModel):
    range_high: float
    range_low: float
    range_span: float
    equilibrium: float          # 50.0% level
    premium_zone: float         # > 50.0%
    discount_zone: float        # < 50.0%
    deep_premium: float         # > 75.0%
    deep_discount: float        # < 25.0%
    current_position_pct: float # 0.0 at low, 1.0 at high
    zone: str                   # "DEEP_DISCOUNT", "DISCOUNT", "EQUILIBRIUM", "PREMIUM", "DEEP_PREMIUM"
    is_valid: bool = True
    description: str = ""


class EquilibriumEngine:
    """
    Computes institutional dealing ranges, equilibrium (50%), and premium/discount zones.
    Rule: Never BUY in Premium, never SELL in Discount.
    """

    @staticmethod
    def calculate_range(candles: list[Candle], lookback: int = 50) -> Optional[DealingRange]:
        if not candles or len(candles) < 10:
            return None

        recent = candles[-lookback:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        range_high = max(highs)
        range_low = min(lows)
        span = range_high - range_low

        if span <= 0:
            return None

        eq = range_low + (span * 0.50)
        deep_disc = range_low + (span * 0.25)
        deep_prem = range_low + (span * 0.75)

        curr_p = candles[-1].close
        pos_pct = max(0.0, min(1.0, (curr_p - range_low) / span))

        if pos_pct >= 0.75:
            zone = "DEEP_PREMIUM"
        elif pos_pct > 0.55:
            zone = "PREMIUM"
        elif pos_pct < 0.25:
            zone = "DEEP_DISCOUNT"
        elif pos_pct < 0.45:
            zone = "DISCOUNT"
        else:
            zone = "EQUILIBRIUM"

        desc = f"Dealing Range [{range_low:.2f} - {range_high:.2f}] | Eq (50%): {eq:.2f} | Current: {zone} ({pos_pct*100:.1f}%)"

        return DealingRange(
            range_high=round(range_high, 2),
            range_low=round(range_low, 2),
            range_span=round(span, 2),
            equilibrium=round(eq, 2),
            premium_zone=round(eq, 2),
            discount_zone=round(eq, 2),
            deep_premium=round(deep_prem, 2),
            deep_discount=round(deep_disc, 2),
            current_position_pct=round(pos_pct, 3),
            zone=zone,
            is_valid=True,
            description=desc
        )

    @staticmethod
    def validate_setup_zone(direction: str, current_price: float, dr: Optional[DealingRange]) -> tuple[bool, str]:
        """
        Validates whether current price is favorable according to institutional PD arrays.
        - LONG setups require Discount or Deep Discount <= 52%
        - SHORT setups require Premium or Deep Premium >= 48%
        """
        if not dr or dr.range_span <= 0:
            return True, "No dealing range active (Neutral)"

        pos_pct = max(0.0, min(1.0, (current_price - dr.range_low) / dr.range_span))

        if direction.upper() == "LONG":
            if pos_pct > 0.55:
                return False, f"LONG Rejected: Price at {pos_pct*100:.1f}% of range is in PREMIUM (Chop/Trap Zone)"
            zone = "DEEP_DISCOUNT" if pos_pct <= 0.25 else "DISCOUNT"
            return True, f"LONG Validated in {zone} ({pos_pct*100:.1f}% of range)"

        elif direction.upper() == "SHORT":
            if pos_pct < 0.45:
                return False, f"SHORT Rejected: Price at {pos_pct*100:.1f}% of range is in DISCOUNT (Chop/Trap Zone)"
            zone = "DEEP_PREMIUM" if pos_pct >= 0.75 else "PREMIUM"
            return True, f"SHORT Validated in {zone} ({pos_pct*100:.1f}% of range)"

        return True, "Direction neutral"
