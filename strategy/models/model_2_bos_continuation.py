import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias
from structure.swings import find_swings
from structure.bos_choch import BosChochEngine
from structure.retest import RetestEngine
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model2BosContinuation(BaseStrategyModel):
    """
    MODEL 2 — BOS CONTINUATION
    Sequence: Strong Trend -> BOS -> Retest -> Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_2",
            name="BOS Continuation",
            description="Trend continuation following established trend structure, confirmed BOS, and level retest"
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
        swings_5m = find_swings(c5, lookback=settings.SWING_LOOKBACK)

        # BOS in trend direction
        bos = BosChochEngine.detect(c5, swings_5m, search_bars=8, trend_bias=trend_15m)
        if not bos.detected or bos.event_type != "BOS" or bos.direction != trend_15m.upper():
            return None

        # Retest of the broken swing level
        retest = RetestEngine.evaluate_retest(
            candles=c5,
            level=bos.broken_level,
            direction=direction,
            break_bar_idx=bos.candle_index,
            atr=atr_5m,
            tolerance_atr=settings.RETEST_TOLERANCE_ATR,
            max_bars_since_break=settings.BARS_BOS_TO_RETEST
        )
        if not retest.detected:
            return None

        obs = OrderBlockEngine.find_order_blocks(symbol, c5, bos)
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

        from indicators.volume import calculate_rvol

        extreme = min(c.low for c in c5[-10:]) if direction == "LONG" else max(c.high for c in c5[-10:])
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
            bos_confirmed=bos.close_confirmed,
            volume_confirmed=confirmations.volume_ok,
            rvol=calculate_rvol(c5),
            risk_reward=levels.risk_reward
        )
        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now_ts = c5[-1].time or int(time.time())
        seq = SetupSequence(
            sequence_id=f"SEQ_M2_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            bos_bar_idx=bos.candle_index,
            retest_bar_idx=retest.candle_index,
            bos_level=bos.broken_level,
            retest_level=retest.retested_level
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
                f"15M Trend: {trend_15m}",
                f"BOS: {bos.description}",
                f"Retest: {retest.description}",
                f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
                f"Setup Score: {score_breakdown.total_score}/100"
            ],
            is_valid=True
        )
