import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from structure.retest import RetestEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model3ObFvg(BaseStrategyModel):
    """
    MODEL 3 — ORDER BLOCK + FVG
    Sequence: Trend Alignment -> Valid OB + FVG Confluence -> Price Returns to Zone -> Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_3",
            name="Order Block + FVG Confluence",
            description="Institutional entry at unmitigated Order Block aligned with Fair Value Gap imbalance"
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

        obs = OrderBlockEngine.find_order_blocks(symbol, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, direction)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, direction)

        # Both OB and FVG must be present for Model 3
        if not active_ob or not active_fvg:
            return None

        # Price must be touching or inside the OB or FVG zone
        curr = c5[-1]
        zone_touched = False
        if direction == "LONG":
            zone_touched = (curr.low <= active_ob.top and curr.close >= active_ob.bottom) or \
                           (curr.low <= active_fvg.top and curr.close >= active_fvg.bottom)
        else:
            zone_touched = (curr.high >= active_ob.bottom and curr.close <= active_ob.top) or \
                           (curr.high >= active_fvg.bottom and curr.close <= active_fvg.top)

        if not zone_touched:
            return None

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

        # Stop loss placed beyond OB boundary + buffer
        extreme = active_ob.bottom if direction == "LONG" else active_ob.top
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
            bos_confirmed=True,
            volume_confirmed=confirmations.volume_ok,
            rvol=c5[-1].volume / max(1.0, c5[-2].volume),
            risk_reward=levels.risk_reward
        )
        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now_ts = c5[-1].time or int(time.time())
        seq = SetupSequence(
            sequence_id=f"SEQ_M3_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            retest_level=active_ob.top if direction == "LONG" else active_ob.bottom
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
                f"Active OB: [{active_ob.bottom:.2f} - {active_ob.top:.2f}]",
                f"Active FVG: [{active_fvg.bottom:.2f} - {active_fvg.top:.2f}]",
                f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
                f"Setup Score: {score_breakdown.total_score}/100"
            ],
            is_valid=True
        )
