import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias, calculate_ema
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model6TrendPullback(BaseStrategyModel):
    """
    MODEL 6 — TREND PULLBACK
    Sequence: Strong Trend -> Shallow Pullback to 20/50 EMA or Order Block -> Reversal Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_6",
            name="Trend Dynamic Pullback",
            description="High-momentum trend continuation entering on pullbacks to dynamic EMA support/resistance"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 20 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        trend_15m = get_trend_bias(c15)
        if trend_15m not in ("Bullish", "Bearish"):
            return None

        direction = "LONG" if trend_15m == "Bullish" else "SHORT"

        # Calculate EMAs on 5m
        closes_5 = [c.close for c in c5]
        ema20 = calculate_ema(closes_5, 20)[-1]
        ema50 = calculate_ema(closes_5, 50)[-1]
        curr = c5[-1]

        # Check pullback touch of 20 or 50 EMA
        pullback_detected = False
        if direction == "LONG":
            # Price pulls back to near EMA 20 or EMA 50
            if (curr.low <= ema20 * 1.002 and curr.close >= ema20 * 0.995) or \
               (curr.low <= ema50 * 1.002 and curr.close >= ema50 * 0.995):
                pullback_detected = True
        else:
            if (curr.high >= ema20 * 0.998 and curr.close <= ema20 * 1.005) or \
               (curr.high >= ema50 * 0.998 and curr.close <= ema50 * 1.005):
                pullback_detected = True

        if not pullback_detected:
            return None

        obs = OrderBlockEngine.find_order_blocks(symbol, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, direction)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, direction)

        confirmations = ConfirmationEngine.evaluate(
            direction=direction,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context,
            active_ob=active_ob,
            active_fvg=active_fvg
        )
        if not confirmations.is_qualified:
            return None

        extreme = min(c.low for c in c5[-4:]) if direction == "LONG" else max(c.high for c in c5[-4:])
        levels = RiskEngine.calculate_levels(
            direction=direction,
            current_price=curr_price,
            extreme_level=extreme,
            atr=atr_5m,
            min_rr=settings.MIN_RISK_REWARD
        )
        if not levels.is_valid:
            return None

        score_breakdown = calculate_setup_score(
            trend_aligned=True,
            trend_neutral=False,
            sweep_confirmed=False,
            bos_confirmed=False,
            volume_confirmed=confirmations.volume_ok,
            rvol=c5[-1].volume / max(1.0, c5[-2].volume),
            risk_reward=levels.risk_reward
        )
        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now_ts = c5[-1].time or int(time.time())
        seq = SetupSequence(
            sequence_id=f"SEQ_M6_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            retest_level=ema20
        )
        self.active_sequences[symbol] = seq

        return StrategyCandidate(
            id=f"{symbol}_{self.model_id}_{direction}_{now_ts}",
            coin=symbol,
            model_id=self.model_id,
            model_name=self.name,
            direction=direction,
            detection_timestamp=now_ts,
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            target_1=levels.target_1,
            target_2=levels.target_2,
            rr=levels.risk_reward,
            setup_score=score_breakdown.total_score,
            score_breakdown=score_breakdown,
            confirmations=confirmations,
            state_sequence=seq,
            reasons=[
                f"Model: {self.name}",
                f"Pullback to EMA 20/50: {ema20:.2f} / {ema50:.2f}",
                f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
                f"Setup Score: {score_breakdown.total_score}/100"
            ],
            is_valid=True
        )
