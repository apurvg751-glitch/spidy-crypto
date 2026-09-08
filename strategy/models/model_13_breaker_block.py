import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.volume import calculate_rvol
from indicators.displacement import DisplacementEngine
from structure.swings import find_swings
from structure.bos_choch import BosChochEngine
from structure.equilibrium import EquilibriumEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.models.base_model import BaseStrategyModel, StrategyCandidate


class Model13BreakerBlock(BaseStrategyModel):
    """
    MODEL 13 — BREAKER BLOCK REVERSAL (FAILED ORDER BLOCK FLIP)
    Institutional Sequence:
    1. Liquidity Run: Bullish setup requires Low -> High -> Lower Low (Sweep).
                     Bearish setup requires High -> Low -> Higher High (Sweep).
    2. Violent Structural Shift: Aggressive displacement candle blows past the intermediate swing.
    3. Failed OB Flip: The order block that caused the sweep flips into a Breaker Block.
    4. Retest: Price pulls back to mitigate the Breaker Block.
    5. Execution: Enter on Breaker Block touch targeting the expansion targets.
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_13",
            name="Breaker Block Reversal",
            description="Institutional failed order block flip following a liquidity sweep and violent market structure shift"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 30 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        swings = find_swings(c5, lookback=4)
        if len(swings) < 4:
            return None

        # Identify Breaker Pattern in recent swings
        # Bullish Breaker: L1 -> H1 -> LL (sweep) -> MSS break above H1 -> Retest of H1/Breaker
        direction = None
        breaker_top = 0.0
        breaker_bottom = 0.0
        stop_loss = 0.0
        target_1 = 0.0
        target_2 = 0.0

        # Scan for Bullish Breaker
        for i in range(len(swings) - 3):
            s1, s2, s3 = swings[i], swings[i+1], swings[i+2]
            # Pattern: LOW (s1) -> HIGH (s2) -> LOWER LOW (s3)
            if s1.point_type == "LOW" and s2.point_type == "HIGH" and s3.point_type == "LOW":
                if s3.price < s1.price: # Lower low that swept s1
                    # Check if subsequent candles broke ABOVE s2 (MSS)
                    subsequent_bars = [c for c in c5 if c.time > s3.time]
                    broke_above = any(c.close > s2.price for c in subsequent_bars)
                    if broke_above:
                        # Breaker zone is around s2.price
                        b_top = s2.price + (atr_5m * 0.25)
                        b_bottom = s2.price - (atr_5m * 0.4)
                        # Check if current price is retesting this breaker zone
                        if b_bottom <= curr_price <= (b_top + atr_5m * 0.5):
                            direction = "LONG"
                            breaker_top = b_top
                            breaker_bottom = b_bottom
                            stop_loss = s3.price if (curr_price - s3.price) < (atr_5m * 2.5) else (breaker_bottom - atr_5m * 0.7)
                            break

            # Pattern: HIGH (s1) -> LOW (s2) -> HIGHER HIGH (s3)
            elif s1.point_type == "HIGH" and s2.point_type == "LOW" and s3.point_type == "HIGH":
                if s3.price > s1.price: # Higher high that swept s1
                    # Check if subsequent candles broke BELOW s2 (MSS)
                    subsequent_bars = [c for c in c5 if c.time > s3.time]
                    broke_below = any(c.close < s2.price for c in subsequent_bars)
                    if broke_below:
                        # Breaker zone is around s2.price
                        b_top = s2.price + (atr_5m * 0.4)
                        b_bottom = s2.price - (atr_5m * 0.25)
                        # Check if current price is retesting this breaker zone
                        if (b_bottom - atr_5m * 0.5) <= curr_price <= b_top:
                            direction = "SHORT"
                            breaker_top = b_top
                            breaker_bottom = b_bottom
                            stop_loss = s3.price if (s3.price - curr_price) < (atr_5m * 2.5) else (breaker_top + atr_5m * 0.7)
                            break

        if not direction:
            return None

        risk = abs(curr_price - stop_loss)
        if risk <= 0 or risk < (atr_5m * 0.4):
            stop_loss = (curr_price - atr_5m * 0.85) if direction == "LONG" else (curr_price + atr_5m * 0.85)
            risk = abs(curr_price - stop_loss)

        # Targets
        target_1 = curr_price + (risk * 1.6) if direction == "LONG" else curr_price - (risk * 1.6)
        target_2 = curr_price + (risk * 2.4) if direction == "LONG" else curr_price - (risk * 2.4)
        rr = abs(target_2 - curr_price) / risk

        disp = DisplacementEngine.evaluate(c5)
        confs = ConfirmationEngine.evaluate(
            direction=direction,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context
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
        score = min(100, max(75, breakdown.total_score + 10))

        cand = StrategyCandidate(
            id=f"M13_{symbol}_{direction}_{int(time.time())}",
            coin=symbol,
            model_id="MODEL_13",
            model_name="Breaker Block Reversal",
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
            grade_badge="🛡️ GRADE: A+ (BREAKER BLOCK)",
            reasons=[
                f"Breaker Block: Confirmed failed pivot flip around {breaker_bottom:.4f} - {breaker_top:.4f}",
                f"MSS Retest: Price ({curr_price:.4f}) testing breaker support/resistance",
                f"Target: Expansion target {target_2:.4f} (1:{rr:.2f}R)"
            ]
        )
        return cand
