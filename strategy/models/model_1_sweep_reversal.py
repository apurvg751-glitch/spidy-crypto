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


class Model1SweepReversal(BaseStrategyModel):
    """
    MODEL 1 — LIQUIDITY SWEEP REVERSAL
    MANDATORY Sequence:
    Liquidity Sweep -> BOS -> Retest -> Confirmation -> READY
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_1",
            name="Liquidity Sweep Reversal",
            description="Institutional reversal following liquidity sweep, structural shift (BOS), and level retest"
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
        sweep = LiquidityEngine.detect_liquidity_sweep(c5, swings_5m, search_bars=8)

        if not sweep.detected:
            return None

        direction = "LONG" if sweep.sweep_type == "BULLISH" else "SHORT"
        trend_15m = get_trend_bias(c15)

        # BOS in trade direction
        trend_bias = "Bullish" if direction == "LONG" else "Bearish"
        bos = BosChochEngine.detect(c5, swings_5m, search_bars=8, trend_bias=trend_bias)

        if not bos.detected or bos.direction != trend_bias.upper():
            return None

        # Retest of the sweep level or BOS broken level
        retest_ref_level = bos.broken_level or sweep.sweep_level
        retest = RetestEngine.evaluate_retest(
            candles=c5,
            level=retest_ref_level,
            direction=direction,
            break_bar_idx=bos.candle_index,
            atr=atr_5m,
            tolerance_atr=settings.RETEST_TOLERANCE_ATR,
            max_bars_since_break=settings.BARS_BOS_TO_RETEST
        )

        # For Model 1, Retest is mandatory
        if not retest.detected:
            # Also check if price is currently retesting the sweep level
            retest = RetestEngine.evaluate_retest(
                candles=c5,
                level=sweep.sweep_level,
                direction=direction,
                break_bar_idx=sweep.candle_index,
                atr=atr_5m,
                tolerance_atr=settings.RETEST_TOLERANCE_ATR,
                max_bars_since_break=settings.BARS_SWEEP_TO_BOS + settings.BARS_BOS_TO_RETEST
            )
            if not retest.detected:
                return None

        # OB & FVG confluence
        obs = OrderBlockEngine.find_order_blocks(symbol, c5, bos)
        active_ob = OrderBlockEngine.get_active_ob(obs, direction)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, direction)

        # 7 Confirmations Gate (Must achieve >= 4/7)
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

        # Risk & Structural Invalidation Stop Loss
        extreme = sweep.extreme_price
        levels = RiskEngine.calculate_levels(
            direction=direction,
            current_price=curr_price,
            extreme_level=extreme,
            atr=atr_5m,
            min_rr=settings.MIN_RISK_REWARD
        )

        if not levels.is_valid:
            return None

        from indicators.volume import calculate_rvol

        # Setup Confidence Scoring (0 - 100)
        score_breakdown = calculate_setup_score(
            trend_aligned=(trend_15m == trend_bias),
            trend_neutral=(trend_15m == "Neutral"),
            sweep_confirmed=sweep.reclaim_confirmed,
            bos_confirmed=bos.close_confirmed,
            volume_confirmed=confirmations.volume_ok,
            rvol=calculate_rvol(c5),
            risk_reward=levels.risk_reward
        )

        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        # Sequence state tracking
        now_ts = c5[-1].time or int(time.time())
        seq = SetupSequence(
            sequence_id=f"SEQ_M1_{symbol}_{now_ts}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            sweep_bar_idx=sweep.candle_index,
            bos_bar_idx=bos.candle_index,
            retest_bar_idx=retest.candle_index,
            sweep_level=sweep.sweep_level,
            extreme_level=sweep.extreme_price,
            bos_level=bos.broken_level,
            retest_level=retest.retested_level
        )
        self.active_sequences[symbol] = seq

        reasons = [
            f"Model: {self.name}",
            f"Liquidity Sweep: {sweep.description}",
            f"BOS: {bos.description}",
            f"Retest: {retest.description}",
            f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
            f"Setup Score: {score_breakdown.total_score}/100"
        ]

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
            reasons=reasons,
            is_valid=True
        )
