from typing import Optional, Literal
from pydantic import BaseModel
from market_data.models import FairValueGap
from structure.order_blocks import OrderBlock


class RetestSnapResult(BaseModel):
    optimal_entry: float
    original_close: float
    discount_pips: float
    entry_type: str  # "FVG_MIDPOINT", "OB_MIDPOINT", "PULLBACK_DISCOUNT"


class RetestSnapper:
    """
    Snaps trade entry to an institutional discount pullback rather than chasing
    the breakout candle close.
    """

    @staticmethod
    def calculate_optimal_entry(
        symbol: str,
        direction: Literal["LONG", "SHORT"],
        current_close: float,
        atr: float,
        active_fvg: Optional[FairValueGap] = None,
        active_ob: Optional[OrderBlock] = None
    ) -> RetestSnapResult:
        decimals = 4 if symbol.upper() == "XRPUSD" else 2

        if direction == "LONG":
            # Target 50% consequent encroachment of FVG
            if active_fvg and active_fvg.bottom < current_close:
                mid = (active_fvg.top + active_fvg.bottom) / 2.0
                if mid < current_close:
                    opt = round(mid, decimals)
                    return RetestSnapResult(
                        optimal_entry=opt,
                        original_close=current_close,
                        discount_pips=round(current_close - opt, decimals),
                        entry_type="FVG_MIDPOINT"
                    )

            # Target 50% midpoint of Bullish Order Block
            if active_ob and active_ob.bottom < current_close:
                mid = (active_ob.top + active_ob.bottom) / 2.0
                if mid < current_close:
                    opt = round(mid, decimals)
                    return RetestSnapResult(
                        optimal_entry=opt,
                        original_close=current_close,
                        discount_pips=round(current_close - opt, decimals),
                        entry_type="OB_MIDPOINT"
                    )

            # Fallback: 0.15x ATR discount pullback
            opt = round(current_close - (0.15 * atr), decimals)
            return RetestSnapResult(
                optimal_entry=opt,
                original_close=current_close,
                discount_pips=round(current_close - opt, decimals),
                entry_type="PULLBACK_DISCOUNT"
            )

        else:  # SHORT
            # Target 50% consequent encroachment of Bearish FVG
            if active_fvg and active_fvg.top > current_close:
                mid = (active_fvg.top + active_fvg.bottom) / 2.0
                if mid > current_close:
                    opt = round(mid, decimals)
                    return RetestSnapResult(
                        optimal_entry=opt,
                        original_close=current_close,
                        discount_pips=round(opt - current_close, decimals),
                        entry_type="FVG_MIDPOINT"
                    )

            # Target 50% midpoint of Bearish Order Block
            if active_ob and active_ob.top > current_close:
                mid = (active_ob.top + active_ob.bottom) / 2.0
                if mid > current_close:
                    opt = round(mid, decimals)
                    return RetestSnapResult(
                        optimal_entry=opt,
                        original_close=current_close,
                        discount_pips=round(opt - current_close, decimals),
                        entry_type="OB_MIDPOINT"
                    )

            # Fallback: 0.15x ATR premium pullback
            opt = round(current_close + (0.15 * atr), decimals)
            return RetestSnapResult(
                optimal_entry=opt,
                original_close=current_close,
                discount_pips=round(opt - current_close, decimals),
                entry_type="PULLBACK_DISCOUNT"
            )
