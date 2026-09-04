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


class Model9LiquiditySweepReversal(BaseStrategyModel):
    """
    MODEL 9 — LIQUIDITY SWEEP REVERSAL (⭐ Core Institutional Strategy)
    MANDATORY Sequence:
    Liquidity Sweep -> Reclaim -> BOS -> Retest -> Confirmation -> READY
    Best Environment: Trend Reversals & Liquidity Grabs
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_9",
            name="Liquidity Sweep Reversal ⭐",
            description="5-step institutional reversal: Liquidity sweep -> range reclaim -> BOS shift -> level retest -> candle confirmation"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 20 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        # 1. Swings & Step 1: Liquidity Sweep
        swings_5m = find_swings(c5, lookback=settings.SWING_LOOKBACK)
        sweep = LiquidityEngine.detect_liquidity_sweep(c5, swings_5m, search_bars=10)

        if not sweep.detected:
            return None

        # 2. Step 2: Reclaim Confirmation (Candle closes back inside range)
        if not sweep.reclaim_confirmed:
            return None

        direction = "LONG" if sweep.sweep_type == "BULLISH" else "SHORT"
        trend_bias = "Bullish" if direction == "LONG" else "Bearish"

        # 3. Step 3: Break of Structure (BOS / CHoCH in direction of reversal)
        bos = BosChochEngine.detect(c5, swings_5m, search_bars=10, trend_bias=trend_bias)
        if not bos.detected:
            return None

        # 4. Step 4: Retest of the broken level or sweep level
        retest_level = bos.broken_level or sweep.sweep_level
        retest = RetestEngine.evaluate_retest(
            candles=c5,
            level=retest_level,
            direction=direction,
            break_bar_idx=bos.candle_index,
            atr=atr_5m,
            tolerance_atr=settings.RETEST_TOLERANCE_ATR,
            max_bars_since_break=10
        )

        if not retest.detected:
            # Fallback: check retest of sweep level itself
            retest = RetestEngine.evaluate_retest(
                candles=c5,
                level=sweep.sweep_level,
                direction=direction,
                break_bar_idx=sweep.candle_index,
                atr=atr_5m,
                tolerance_atr=settings.RETEST_TOLERANCE_ATR,
                max_bars_since_break=12
            )
            if not retest.detected:
                return None

        # 5. Step 5: Structure Confirmation & 7 Confirmations Gate (>= 4/7)
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

        # 6. Invalidation Stop Loss & Dynamic Targets
        levels = RiskEngine.calculate_levels(
            direction=direction,
            current_price=curr_price,
            extreme_level=sweep.extreme_price,
            atr=atr_5m,
            min_rr=settings.MIN_RISK_REWARD
        )

        if not levels.is_valid:
            return None

        from indicators.volume import calculate_rvol

        trend_15m = get_trend_bias(c15)
        score_breakdown = calculate_setup_score(
            trend_aligned=(trend_15m == ("Bullish" if direction == "LONG" else "Bearish")),
            trend_neutral=(trend_15m == "Neutral"),
            sweep_confirmed=True,
            bos_confirmed=True,
            volume_confirmed=confirmations.volume_ok,
            rvol=calculate_rvol(c5),
            risk_reward=levels.risk_reward
        )

        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now = int(time.time())
        sequence = SetupSequence(
            sequence_id=f"SEQ_M9_{symbol}_{now}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            sweep_bar_idx=sweep.candle_index,
            sweep_level=sweep.sweep_level,
            extreme_level=sweep.extreme_price,
            bos_level=bos.broken_level
        )
        self.active_sequences[symbol] = sequence
        reasons = [
            "Model 9: Liquidity Sweep Reversal ⭐",
            f"Sweep & Reclaim: {sweep.description}",
            f"BOS Shift: {bos.description}",
            f"Retest: Confirmed at {retest_level:.2f}",
            f"Confirmations: {confirmations.passed_count}/7 ({confirmations.rating})",
            f"Score: {score_breakdown.total_score}/100"
        ]

        return StrategyCandidate(
            id=f"{symbol}_{self.model_id}_{direction}_{now}",
            coin=symbol,
            model_id=self.model_id,
            model_name=self.name,
            direction=direction,
            detection_timestamp=now,
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            target_1=levels.target_1,
            target_2=levels.target_2,
            rr=levels.risk_reward,
            setup_score=score_breakdown.total_score,
            score_breakdown=score_breakdown,
            confirmations=confirmations,
            state_sequence=sequence,
            reasons=reasons,
            is_valid=True
        )
