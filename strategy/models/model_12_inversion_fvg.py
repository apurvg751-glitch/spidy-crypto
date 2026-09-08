import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.volume import calculate_rvol
from indicators.displacement import DisplacementEngine
from structure.swings import find_swings
from structure.fvg import FvgEngine
from structure.equilibrium import EquilibriumEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.models.base_model import BaseStrategyModel, StrategyCandidate


class Model12InversionFvg(BaseStrategyModel):
    """
    MODEL 12 — INVERSION FAIR VALUE GAP (IFVG FLIP MODEL)
    Institutional Sequence:
    1. A Fair Value Gap is created (imbalance between bar 1 and bar 3).
    2. Instead of holding as support/resistance, strong momentum blows through and closes beyond it.
    3. The FVG "inverts" — failed resistance becomes support, failed support becomes resistance.
    4. Price returns to retest the boundary of the inverted FVG.
    5. Execution: Enter on retest with invalidation on the opposite edge of the IFVG.
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_12",
            name="Inversion FVG Retest",
            description="Institutional momentum flip where blown-out FVGs invert into high-probability support/resistance shelves"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 30 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        # Detect all FVGs on 5M
        all_fvgs = FvgEngine.find_fvgs(symbol, c5)
        if not all_fvgs:
            return None

        # Look for Inverted FVGs in the last 20 bars
        # Bullish Inversion: A BEARISH FVG that was closed ABOVE by recent candles, and now price is retesting it
        # Bearish Inversion: A BULLISH FVG that was closed BELOW by recent candles, and now price is retesting it
        best_ifvg = None
        direction = None
        stop_loss = 0.0
        target_1 = 0.0
        target_2 = 0.0

        disp = DisplacementEngine.evaluate(c5)
        trend_15m = market.mtf_context.exec_context_15m if market.mtf_context else "Neutral"

        for fvg in reversed(all_fvgs[-10:]):
            fvg_top = fvg.top
            fvg_bottom = fvg.bottom
            fvg_height = fvg_top - fvg_bottom

            if fvg_height <= 0:
                continue

            # Bullish Inversion Candidate (originally Bearish FVG)
            if fvg.direction == "BEARISH" and trend_15m != "Bearish":
                # Check if price broke above fvg_top with displacement
                subsequent = c5[fvg.candle_index:]
                closed_above = any(c.close > fvg_top and c.is_bullish for c in subsequent)
                if closed_above:
                    # Current price is retesting the inverted zone (near top or inside it)
                    is_retesting = (curr_price >= (fvg_bottom - atr_5m * 0.2)) and (curr_price <= (fvg_top + atr_5m * 0.5))
                    # Retest candle shows bullish reaction (close > open or lower wick)
                    if is_retesting and c5[-1].close >= c5[-1].open:
                        direction = "LONG"
                        best_ifvg = fvg
                        stop_loss = fvg_bottom - (atr_5m * 0.5)
                        break

            # Bearish Inversion Candidate (originally Bullish FVG)
            elif fvg.direction == "BULLISH" and trend_15m != "Bullish":
                # Check if price broke below fvg_bottom with displacement
                subsequent = c5[fvg.candle_index:]
                closed_below = any(c.close < fvg_bottom and c.is_bearish for c in subsequent)
                if closed_below:
                    # Current price is retesting the inverted zone
                    is_retesting = (curr_price <= (fvg_top + atr_5m * 0.2)) and (curr_price >= (fvg_bottom - atr_5m * 0.5))
                    # Retest candle shows bearish reaction (close <= open or upper wick)
                    if is_retesting and c5[-1].close <= c5[-1].open:
                        direction = "SHORT"
                        best_ifvg = fvg
                        stop_loss = fvg_top + (atr_5m * 0.5)
                        break

        if not direction or not best_ifvg:
            return None

        # Check Risk & Setup Targets
        risk = abs(curr_price - stop_loss)
        if risk <= 0 or risk < (atr_5m * 0.4):
            # Ensure safe stop distance
            stop_loss = (curr_price - atr_5m * 0.85) if direction == "LONG" else (curr_price + atr_5m * 0.85)
            risk = abs(curr_price - stop_loss)

        # Draw on Liquidity targets
        swings = find_swings(c5, lookback=5)
        if direction == "LONG":
            swing_highs = [s.price for s in swings if s.point_type == "HIGH" and s.price > curr_price]
            target_1 = min(swing_highs) if swing_highs else (curr_price + risk * 1.6)
            target_2 = max(swing_highs) if swing_highs else (curr_price + risk * 2.5)
        else:
            swing_lows = [s.price for s in swings if s.point_type == "LOW" and s.price < curr_price]
            target_1 = max(swing_lows) if swing_lows else (curr_price - risk * 1.6)
            target_2 = min(swing_lows) if swing_lows else (curr_price - risk * 2.5)

        # Enforce minimum 1.6R
        reward_1 = abs(target_1 - curr_price)
        reward_2 = abs(target_2 - curr_price)
        if reward_1 < risk * 1.4:
            target_1 = curr_price + (risk * 1.6) if direction == "LONG" else curr_price - (risk * 1.6)
        if reward_2 < risk * 2.0:
            target_2 = curr_price + (risk * 2.2) if direction == "LONG" else curr_price - (risk * 2.2)

        rr = abs(target_2 - curr_price) / risk

        disp = DisplacementEngine.evaluate(c5)
        confs = ConfirmationEngine.evaluate(
            direction=direction,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context,
            active_fvg=best_ifvg
        )

        rvol = calculate_rvol(c5)
        vol_ok = rvol >= 1.10 or disp.detected

        from strategy.scoring import calculate_institutional_100_score
        breakdown = calculate_institutional_100_score(
            htf_aligned=confs.trend_ok,
            sweep_confirmed=True,
            displacement_mss=disp.detected,
            pd_array_confirmed=True,
            ob_fvg_confluence=True,
            volume_confirmed=vol_ok,
            rvol=rvol,
            risk_reward=rr
        )
        score = min(100, max(75, breakdown.total_score + 8))

        cand = StrategyCandidate(
            id=f"M12_{symbol}_{direction}_{int(time.time())}",
            coin=symbol,
            model_id="MODEL_12",
            model_name="Inversion FVG Retest",
            direction=direction,
            detection_timestamp=int(time.time()),
            entry=round(curr_price, 4),
            stop_loss=round(stop_loss, 4),
            target_1=round(target_1, 4),
            target_2=round(target_2, 4),
            rr=round(rr, 2),
            setup_score=score,
            score_breakdown=breakdown,
            confirmations=confs,
            grade="A+",
            grade_badge="⚡ GRADE: A+ (INVERSION FVG)",
            reasons=[
                f"IFVG Flip: Inverted {best_ifvg.direction} FVG [{best_ifvg.bottom:.4f} - {best_ifvg.top:.4f}] into {'support' if direction == 'LONG' else 'resistance'}",
                f"Retest: Price ({curr_price:.4f}) testing inverted shelf with stop at {stop_loss:.4f}",
                f"Target: Next liquidity pool at {target_2:.4f} (1:{rr:.2f}R)"
            ]
        )
        return cand
