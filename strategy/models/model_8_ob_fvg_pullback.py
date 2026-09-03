import time
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.moving_averages import get_trend_bias
from indicators.candles import is_rejection_candle
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.state_machine import SetupSequence
from risk_engine.risk_calculator import RiskEngine
from .base_model import BaseStrategyModel, StrategyCandidate


class Model8ObFvgPullback(BaseStrategyModel):
    """
    MODEL 8 — ORDER BLOCK + FVG PULLBACK
    MANDATORY Sequence:
    Valid OB + FVG -> Price Returns (Pullback) -> Rejection -> Confirmation -> READY
    Best Environment: Pullbacks during trending conditions
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_8",
            name="Order Block + FVG Pullback",
            description="Trend pullback entry into unmitigated Order Block + FVG confluence with rejection candle confirmation"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 20 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        # 1. Trend environment for pullback
        trend_15m = get_trend_bias(c15)
        if trend_15m not in ("Bullish", "Bearish"):
            return None

        direction = "LONG" if trend_15m == "Bullish" else "SHORT"

        # 2. Step 1: Valid OB + FVG Confluence
        obs = OrderBlockEngine.find_order_blocks(symbol, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, direction)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, direction)

        if not active_ob or not active_fvg:
            return None

        # Confluence check: OB and FVG must overlap or be adjacent within 0.5 ATR
        ob_mid = (active_ob.top + active_ob.bottom) / 2.0
        fvg_mid = (active_fvg.top + active_fvg.bottom) / 2.0
        if abs(ob_mid - fvg_mid) > (atr_5m * 1.5):
            return None

        # 3. Step 2: Price Returns (Pullback to zone)
        curr = c5[-1]
        prev = c5[-2]
        zone_top = max(active_ob.top, active_fvg.top)
        zone_bottom = min(active_ob.bottom, active_fvg.bottom)

        price_returned = False
        if direction == "LONG":
            price_returned = (curr.low <= zone_top and curr.low >= zone_bottom - (atr_5m * 0.35)) or \
                             (prev.low <= zone_top and prev.low >= zone_bottom - (atr_5m * 0.35))
        else:
            price_returned = (curr.high >= zone_bottom and curr.high <= zone_top + (atr_5m * 0.35)) or \
                             (prev.high >= zone_bottom and prev.high <= zone_top + (atr_5m * 0.35))

        if not price_returned:
            return None

        # 4. Step 3: Rejection Wick off the Zone
        has_rejection = False
        for c in (curr, prev):
            if direction == "LONG" and (c.lower_wick >= c.total_range * 0.25):
                has_rejection = True
                break
            elif direction == "SHORT" and (c.upper_wick >= c.total_range * 0.25):
                has_rejection = True
                break

        if not has_rejection:
            return None

        # 5. Step 4: Candle Confirmation + 7 Confirmations Gate (>= 4/7)
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

        # 6. Risk, Structural Stop, Dynamic Targets
        stop_level = (zone_bottom - atr_5m * 0.25) if direction == "LONG" else (zone_top + atr_5m * 0.25)
        levels = RiskEngine.calculate_levels(
            direction=direction,
            current_price=curr_price,
            extreme_level=stop_level,
            atr=atr_5m,
            min_rr=settings.MIN_RISK_REWARD
        )

        if not levels.is_valid:
            return None

        score_breakdown = calculate_setup_score(
            trend_aligned=(trend_15m in ("Bullish", "Bearish")),
            trend_neutral=(trend_15m == "Neutral"),
            sweep_confirmed=True,
            bos_confirmed=True,
            volume_confirmed=confirmations.volume_ok,
            rvol=atr_5m,
            risk_reward=levels.risk_reward
        )

        if score_breakdown.total_score < settings.MIN_SETUP_SCORE:
            return None

        now = int(time.time())
        sequence = SetupSequence(
            sequence_id=f"SEQ_M8_{symbol}_{now}",
            symbol=symbol,
            model_id=self.model_id,
            direction=direction,
            current_state="READY",
            extreme_level=stop_level
        )
        self.active_sequences[symbol] = sequence
        reasons = [
            "Model 8: Order Block + FVG Pullback",
            f"OB: Demand [{active_ob.bottom:.2f} - {active_ob.top:.2f}]" if direction == "LONG" else f"OB: Supply [{active_ob.bottom:.2f} - {active_ob.top:.2f}]",
            f"FVG: [{active_fvg.bottom:.2f} - {active_fvg.top:.2f}] (Confluence Confirmed)",
            "Pullback & Rejection: Confirmed off zone",
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
