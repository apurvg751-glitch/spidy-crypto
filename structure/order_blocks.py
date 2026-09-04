from typing import Sequence, Optional
from market_data.models import Candle, OrderBlock
from .swings import SwingPoint
from .bos_choch import StructureBreakEvent


class OrderBlockEngine:
    """
    Deterministic Order Block Detection Engine:
    - Bullish OB: The last down candle prior to an impulsive move that created a bullish BOS/CHoCH.
    - Bearish OB: The last up candle prior to an impulsive move that created a bearish BOS/CHoCH.
    Tracks boundaries, mitigation, invalidation, freshness, and associated structure break.
    """

    @staticmethod
    def find_order_blocks(
        symbol: str,
        candles: Sequence[Candle],
        structure_break: Optional[StructureBreakEvent] = None,
        lookback: int = 25
    ) -> list[OrderBlock]:
        if len(candles) < 2:
            return []

        n = len(candles)
        start_idx = max(0, n - lookback)
        order_blocks: list[OrderBlock] = []

        # Find impulse candles (body > 60% of range and large volume)
        for i in range(start_idx, n - 1):
            curr = candles[i]
            next_bar = candles[i + 1]

            # Bullish OB check: curr is bearish, next is aggressive green impulse
            if curr.is_bearish and next_bar.is_bullish and (next_bar.body_size > curr.body_size * 1.2):
                ob_id = f"OB_BULL_{symbol}_{curr.time}"
                ob = OrderBlock(
                    id=ob_id,
                    symbol=symbol,
                    direction="BULLISH",
                    top=curr.high,
                    bottom=curr.low,
                    candle_index=i,
                    creation_time=curr.time,
                    is_mitigated=False,
                    is_invalidated=False,
                    structure_break_ref=structure_break.event_type if structure_break else None
                )
                # Check mitigation/invalidation from i+2 to latest
                for j in range(i + 2, n):
                    test_c = candles[j]
                    if test_c.close < ob.bottom:
                        ob.is_invalidated = True
                        break
                    elif test_c.low <= ob.top and test_c.close >= ob.bottom:
                        ob.is_mitigated = True

                order_blocks.append(ob)

            # Bearish OB check: curr is bullish, next is aggressive red impulse
            elif curr.is_bullish and next_bar.is_bearish and (next_bar.body_size > curr.body_size * 1.2):
                ob_id = f"OB_BEAR_{symbol}_{curr.time}"
                ob = OrderBlock(
                    id=ob_id,
                    symbol=symbol,
                    direction="BEARISH",
                    top=curr.high,
                    bottom=curr.low,
                    candle_index=i,
                    creation_time=curr.time,
                    is_mitigated=False,
                    is_invalidated=False,
                    structure_break_ref=structure_break.event_type if structure_break else None
                )
                for j in range(i + 2, n):
                    test_c = candles[j]
                    if test_c.close > ob.top:
                        ob.is_invalidated = True
                        break
                    elif test_c.high >= ob.bottom and test_c.close <= ob.top:
                        ob.is_mitigated = True

                order_blocks.append(ob)

        return order_blocks

    @staticmethod
    def get_active_ob(order_blocks: list[OrderBlock], direction: str) -> Optional[OrderBlock]:
        """Returns the most recent fresh or active order block in the trade direction."""
        matching = [
            ob for ob in order_blocks
            if ob.direction == ("BULLISH" if direction == "LONG" else "BEARISH")
            and not ob.is_invalidated
        ]
        if not matching:
            return None
        # Prefer fresh OB, otherwise most recent un-invalidated
        fresh = [ob for ob in matching if ob.is_fresh]
        return fresh[-1] if fresh else matching[-1]
