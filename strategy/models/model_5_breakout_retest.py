import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias
from structure.retest import RetestEngine
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model5BreakoutRetest(BaseStrategyModel):
    """
    MODEL 5 — BREAKOUT RETEST
    Sequence: Range Consolidation -> Clean Breakout -> Retest of Boundary -> Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_5",
            name="Range Breakout Retest",
            description="Expansion from established consolidation range followed by boundary retest"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 25 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        # Identify consolidation range (lookback 15 to 5 bars ago)
        range_candles = c5[-22:-5]
        if len(range_candles) < 10:
            return None

        range_high = max(c.high for c in range_candles)
        range_low = min(c.low for c in range_candles)
        range_height = range_high - range_low

        # Range should be relatively tight (< 3x ATR)
        if range_height > (atr_5m * 4.0):
            return None

        # Check for breakout in recent bars (-5 to -2)
        breakout_dir = None
        break_bar_idx = -1
        break_level = 0.0

        for i in range(len(c5) - 5, len(c5) - 1):
            bar = c5[i]
            if bar.close > range_high:
                breakout_dir = "LONG"
                break_bar_idx = i
                break_level = range_high
                break
            elif bar.close < range_low:
                breakout_dir = "SHORT"
                break_bar_idx = i
                break_level = range_low
                break

        if not breakout_dir:
            return None

        # Retest of the broken range boundary
        retest = RetestEngine.evaluate_retest(
            candles=c5,
            level=break_level,
            direction=breakout_dir,
            break_bar_idx=break_bar_idx,
            atr=atr_5m,
            tolerance_atr=settings.RETEST_TOLERANCE_ATR,
            max_bars_since_break=6
        )
        if not retest.detected:
            return None

        obs = OrderBlockEngine.find_order_blocks(symbol, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, breakout_dir)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, breakout_dir)

        confirmations = ConfirmationEngine.evaluate(
            direction=breakout_dir,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context,
            active_ob=active_ob,
            active_fvg=active_fvg
        )
        if not confirmations.is_qualified:
            return None

        trend_15m = get_trend_bias(c15)
        extreme = range_low if breakout_dir == "LONG" else range_high
        levels = RiskEngine.calculate_levels(
            direction=breakout_dir,
            current_price=curr_price,
            extreme_level=extreme,
            atr=atr_5m,
            min_rr=settings.MIN_RISK_REWARD
        )
        if not levels.is_valid:
            return None

        score_breakdown = calculate_setup_score(
            trend_aligned=(trend_15m == ("Bullish" if breakout_dir == "LONG" else "Bearish")),
            trend_neutral=(trend_15m == "Neutral"),
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
            sequence_id=f"SEQ_M5_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=breakout_dir,
            current_state="READY",
            bos_bar_idx=break_bar_idx,
            retest_bar_idx=retest.candle_index,
            bos_level=break_level,
            retest_level=retest.retested_level
        )
        self.active_sequences[symbol] = seq

        return StrategyCandidate(
            id=f"{symbol}_{self.model_id}_{breakout_dir}_{now_ts}",
            coin=symbol,
            model_id=self.model_id,
            model_name=self.name,
            direction=breakout_dir,
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
                f"Breakout Level: {break_level:.2f}",
                f"Retest: {retest.description}",
                f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
                f"Setup Score: {score_breakdown.total_score}/100"
            ],
            is_valid=True
        )
