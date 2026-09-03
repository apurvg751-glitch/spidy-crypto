from typing import Sequence, Optional
from market_data.models import Candle, FairValueGap


class FvgEngine:
    """
    Deterministic Fair Value Gap (FVG) Engine:
    - 3-candle imbalance detection.
    - Bullish FVG: candle[i].low > candle[i-2].high.
    - Bearish FVG: candle[i].high < candle[i-2].low.
    Tracks boundaries, fill percentage, mitigation, and invalidation.
    """

    @staticmethod
    def find_fvgs(
        symbol: str,
        candles: Sequence[Candle],
        lookback: int = 30
    ) -> list[FairValueGap]:
        if len(candles) < 3:
            return []

        n = len(candles)
        start_idx = max(2, n - lookback)
        fvgs: list[FairValueGap] = []

        for i in range(start_idx, n):
            c0 = candles[i - 2]
            c1 = candles[i - 1]
            c2 = candles[i]

            # Bullish FVG: gap between c0.high and c2.low
            if c2.low > c0.high:
                gap_size = c2.low - c0.high
                if gap_size > (c1.total_range * 0.15):
                    fvg_id = f"FVG_BULL_{symbol}_{c1.time}"
                    fvg = FairValueGap(
                        id=fvg_id,
                        symbol=symbol,
                        direction="BULLISH",
                        top=c2.low,
                        bottom=c0.high,
                        candle_index=i - 1,
                        creation_time=c1.time,
                        fill_pct=0.0,
                        is_mitigated=False,
                        is_invalidated=False
                    )
                    # Check subsequent price action for mitigation/fill
                    for j in range(i + 1, n):
                        test_c = candles[j]
                        if test_c.close < fvg.bottom:
                            fvg.is_invalidated = True
                            fvg.fill_pct = 100.0
                            break
                        elif test_c.low <= fvg.top:
                            fvg.is_mitigated = True
                            penetrated = fvg.top - max(test_c.low, fvg.bottom)
                            fill = (penetrated / max(fvg.top - fvg.bottom, 1e-6)) * 100.0
                            fvg.fill_pct = max(fvg.fill_pct, min(round(fill, 1), 100.0))

                    fvgs.append(fvg)

            # Bearish FVG: gap between c2.high and c0.low
            elif c2.high < c0.low:
                gap_size = c0.low - c2.high
                if gap_size > (c1.total_range * 0.15):
                    fvg_id = f"FVG_BEAR_{symbol}_{c1.time}"
                    fvg = FairValueGap(
                        id=fvg_id,
                        symbol=symbol,
                        direction="BEARISH",
                        top=c0.low,
                        bottom=c2.high,
                        candle_index=i - 1,
                        creation_time=c1.time,
                        fill_pct=0.0,
                        is_mitigated=False,
                        is_invalidated=False
                    )
                    for j in range(i + 1, n):
                        test_c = candles[j]
                        if test_c.close > fvg.top:
                            fvg.is_invalidated = True
                            fvg.fill_pct = 100.0
                            break
                        elif test_c.high >= fvg.bottom:
                            fvg.is_mitigated = True
                            penetrated = min(test_c.high, fvg.top) - fvg.bottom
                            fill = (penetrated / max(fvg.top - fvg.bottom, 1e-6)) * 100.0
                            fvg.fill_pct = max(fvg.fill_pct, min(round(fill, 1), 100.0))

                    fvgs.append(fvg)

        return fvgs

    @staticmethod
    def get_active_fvg(fvgs: list[FairValueGap], direction: str) -> Optional[FairValueGap]:
        matching = [
            fvg for fvg in fvgs
            if fvg.direction == ("BULLISH" if direction == "LONG" else "BEARISH")
            and not fvg.is_invalidated
        ]
        if not matching:
            return None
        # Return most recent unmitigated or partially filled
        unmitigated = [fvg for fvg in matching if not fvg.is_mitigated or fvg.fill_pct < 50.0]
        return unmitigated[-1] if unmitigated else matching[-1]
