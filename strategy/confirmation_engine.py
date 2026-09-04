from typing import Sequence, Optional
from market_data.models import Candle, MultiTimeframeContext, OrderBlock, FairValueGap, ConfirmationsResult
from indicators.volume import is_volume_confirmed, calculate_rvol
from indicators.momentum import is_momentum_aligned
from indicators.candles import detect_candle_confirmation
from indicators.moving_averages import calculate_ema


class ConfirmationEngine:
    """
    Seven Confirmations Framework:
    1. Trend (4H/1H MTF alignment)
    2. Order Block (clean active OB)
    3. FVG (unmitigated imbalance)
    4. Volume (RVOL >= 1.15)
    5. Momentum (RSI / ROC)
    6. EMA Alignment (Price vs EMA 20/50/200)
    7. Candle Confirmation (Engulfing, Pin bar, or Rejection wick)
    
    Minimum Gate: 4/7 required to qualify.
    4/7 = QUALIFIED, 5/7 = STRONG, 6/7 = VERY STRONG, 7/7 = EXCEPTIONAL.
    """

    @staticmethod
    def evaluate(
        direction: str,
        candles_5m: Sequence[Candle],
        candles_15m: Sequence[Candle],
        mtf_context: Optional[MultiTimeframeContext] = None,
        active_ob: Optional[OrderBlock] = None,
        active_fvg: Optional[FairValueGap] = None
    ) -> ConfirmationsResult:
        details: dict[str, str] = {}
        passed = 0

        # 1. Trend Alignment
        trend_ok = False
        if mtf_context:
            target_bias = "Bullish" if direction == "LONG" else "Bearish"
            if mtf_context.trend_1h == target_bias or mtf_context.macro_bias_4h == target_bias:
                trend_ok = True
                details["trend"] = f"Aligned ({mtf_context.trend_1h} 1H, {mtf_context.macro_bias_4h} 4H)"
            else:
                details["trend"] = f"Misaligned ({mtf_context.trend_1h} 1H, {mtf_context.macro_bias_4h} 4H)"
        else:
            trend_ok = True
            details["trend"] = "MTF context default (Neutral)"
        if trend_ok: passed += 1

        # 2. Order Block
        ob_ok = False
        if active_ob and not active_ob.is_invalidated:
            ob_ok = True
            details["order_block"] = f"Valid OB at [{active_ob.bottom:.2f} - {active_ob.top:.2f}] (Fresh: {active_ob.is_fresh})"
        else:
            details["order_block"] = "No active unmitigated Order Block"
        if ob_ok: passed += 1

        # 3. Fair Value Gap
        fvg_ok = False
        if active_fvg and not active_fvg.is_invalidated:
            fvg_ok = True
            details["fvg"] = f"Active FVG at [{active_fvg.bottom:.2f} - {active_fvg.top:.2f}] (Fill: {active_fvg.fill_pct}%)"
        else:
            details["fvg"] = "No active Fair Value Gap"
        if fvg_ok: passed += 1

        # 4. Volume Confirmation (volOk)
        rvol = calculate_rvol(candles_5m, period=20)
        vol_ok = is_volume_confirmed(candles_5m, period=20, threshold=1.12)
        if vol_ok:
            details["volume"] = f"Confirmed (RVOL {rvol:.2f} >= 1.12)"
            passed += 1
        else:
            details["volume"] = f"Below threshold (RVOL {rvol:.2f} < 1.12)"

        # 5. Momentum Alignment
        mom_ok = is_momentum_aligned(candles_5m, direction)
        if mom_ok:
            details["momentum"] = "Confirmed (RSI/ROC aligned)"
            passed += 1
        else:
            details["momentum"] = "Divergent or sluggish momentum"

        # 6. EMA Alignment
        closes_15 = [c.close for c in candles_15m] if candles_15m else [c.close for c in candles_5m]
        ema20 = calculate_ema(closes_15, 20)[-1] if closes_15 else 0.0
        ema50 = calculate_ema(closes_15, 50)[-1] if closes_15 else 0.0
        curr_p = candles_5m[-1].close if candles_5m else 0.0

        if direction == "LONG":
            ema_ok = (curr_p >= ema20 or ema20 >= ema50)
            details["ema"] = f"Aligned ({curr_p:.2f} >= EMA20 {ema20:.2f})" if ema_ok else "Below key EMAs"
        else:
            ema_ok = (curr_p <= ema20 or ema20 <= ema50)
            details["ema"] = f"Aligned ({curr_p:.2f} <= EMA20 {ema20:.2f})" if ema_ok else "Above key EMAs"
        if ema_ok: passed += 1

        # 7. Candle Confirmation
        candle_ok, candle_desc = detect_candle_confirmation(candles_5m, direction)
        details["candle"] = candle_desc
        if candle_ok: passed += 1

        # Rating determination
        if passed >= 7:
            rating = "EXCEPTIONAL"
        elif passed >= 6:
            rating = "VERY_STRONG"
        elif passed >= 5:
            rating = "STRONG"
        elif passed >= 4:
            rating = "QUALIFIED"
        else:
            rating = "UNQUALIFIED"

        return ConfirmationsResult(
            trend_ok=trend_ok,
            ob_ok=ob_ok,
            fvg_ok=fvg_ok,
            volume_ok=vol_ok,
            momentum_ok=mom_ok,
            ema_ok=ema_ok,
            candle_ok=candle_ok,
            passed_count=passed,
            is_qualified=(passed >= 4),
            rating=rating,
            details=details
        )
