import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias
from structure.swings import find_swings
from structure.liquidity import LiquidityEngine
from structure.bos_choch import BosChochEngine
from structure.retest import RetestEngine
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model4ChochReversal(BaseStrategyModel):
    """
    MODEL 4 — CHoCH REVERSAL
    Sequence: Liquidity Event -> Change of Character (CHoCH) -> Retest -> Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_4",
            name="CHoCH Trend Reversal",
            description="Structural trend change triggered by liquidity sweep and confirmed Change of Character (CHoCH)"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 20 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        swings_5m = find_swings(c5, lookback=settings.SWING_LOOKBACK)
        trend_15m = get_trend_bias(c15)

        # Detect CHoCH
        choch = BosChochEngine.detect(c5, swings_5m, search_bars=8, trend_bias=trend_15m)
        if not choch.detected or choch.event_type != "CHOCH":
            return None

        direction = "LONG" if choch.direction == "BULLISH" else "SHORT"

        # Check for supporting liquidity event
        sweep = LiquidityEngine.detect_liquidity_sweep(c5, swings_5m, search_bars=10)

        # Retest of the CHoCH pivot level
        retest = RetestEngine.evaluate_retest(
            candles=c5,
            level=choch.broken_level,
            direction=direction,
            break_bar_idx=choch.candle_index,
            atr=atr_5m,
            tolerance_atr=settings.RETEST_TOLERANCE_ATR,
            max_bars_since_break=settings.BARS_BOS_TO_RETEST
        )
        if not retest.detected:
            return None

        obs = OrderBlockEngine.find_order_blocks(symbol, c5, choch)
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

        extreme = sweep.extreme_price if sweep.detected else (
            min(c.low for c in c5[-6:]) if direction == "LONG" else max(c.high for c in c5[-6:])
        )
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
            trend_aligned=(trend_15m == ("Bullish" if direction == "LONG" else "Bearish")),
            trend_neutral=(trend_15m == "Neutral"),
            sweep_confirmed=sweep.detected,
            bos_confirmed=True,
            volume_confirmed=confirmations.volume_ok,
            rvol=c5[-1].volume / max(1.0, c5[-2].volume),
            risk_reward=levels.risk_reward
        )
        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now_ts = c5[-1].time or int(time.time())
        seq = SetupSequence(
            sequence_id=f"SEQ_M4_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            bos_bar_idx=choch.candle_index,
            retest_bar_idx=retest.candle_index,
            bos_level=choch.broken_level,
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
                f"CHoCH Break: {choch.description}",
                f"Retest: {retest.description}",
                f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
                f"Setup Score: {score_breakdown.total_score}/100"
            ],
            is_valid=True
        )
