from typing import Sequence, Literal
from pydantic import BaseModel
from market_data.models import Candle
from .swings import SwingPoint, find_swings


class MarketStructureState(BaseModel):
    bias: Literal["Bullish", "Bearish", "Ranging"]
    major_bias: Literal["Bullish", "Bearish", "Ranging"]
    internal_bias: Literal["Bullish", "Bearish", "Ranging"]
    latest_swing_high: float = 0.0
    latest_swing_low: float = 0.0
    swings: list[SwingPoint] = []
    description: str = ""


class MarketStructureEngine:
    """Evaluates macro and internal market structure (HH/HL/LH/LL sequences)."""

    @staticmethod
    def analyze(candles: Sequence[Candle]) -> MarketStructureState:
        if len(candles) < 15:
            return MarketStructureState(
                bias="Ranging",
                major_bias="Ranging",
                internal_bias="Ranging",
                description="Insufficient candles"
            )

        # 1. Internal swings (lookback = 2-3)
        internal_swings = find_swings(candles, lookback=3, is_major=False)
        # 2. Major swings (lookback = 5)
        major_swings = find_swings(candles, lookback=5, is_major=True)

        internal_bias = MarketStructureEngine._determine_bias(internal_swings)
        major_bias = MarketStructureEngine._determine_bias(major_swings)

        # Primary bias gives precedence to major structure, confirmed by internal
        primary_bias = major_bias if major_bias != "Ranging" else internal_bias

        latest_high = 0.0
        latest_low = 0.0
        for s in reversed(internal_swings):
            if s.point_type == "HIGH" and latest_high == 0.0:
                latest_high = s.price
            elif s.point_type == "LOW" and latest_low == 0.0:
                latest_low = s.price
            if latest_high > 0 and latest_low > 0:
                break

        desc = f"Structure {primary_bias} (Major: {major_bias}, Internal: {internal_bias})"

        return MarketStructureState(
            bias=primary_bias,
            major_bias=major_bias,
            internal_bias=internal_bias,
            latest_swing_high=latest_high,
            latest_swing_low=latest_low,
            swings=internal_swings,
            description=desc
        )

    @staticmethod
    def _determine_bias(swings: list[SwingPoint]) -> Literal["Bullish", "Bearish", "Ranging"]:
        if len(swings) < 3:
            return "Ranging"

        recent = swings[-4:]
        labels = [s.structure_label for s in recent if s.structure_label]

        hh_count = labels.count("HH")
        hl_count = labels.count("HL")
        lh_count = labels.count("LH")
        ll_count = labels.count("LL")

        if (hh_count + hl_count) >= 2 and (lh_count + ll_count) == 0:
            return "Bullish"
        elif (lh_count + ll_count) >= 2 and (hh_count + hl_count) == 0:
            return "Bearish"
        elif hh_count > 0 and hl_count > 0:
            return "Bullish"
        elif lh_count > 0 and ll_count > 0:
            return "Bearish"

        return "Ranging"
