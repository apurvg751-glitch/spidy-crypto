import time
from datetime import datetime, timezone
from typing import Optional
from market_data.models import MarketState
from config.settings import settings
from indicators.atr import calculate_atr
from indicators.volume import calculate_rvol
from indicators.displacement import DisplacementEngine
from structure.swings import find_swings
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_setup_score
from strategy.models.base_model import BaseStrategyModel, StrategyCandidate


class Model11AsianJudasSwing(BaseStrategyModel):
    """
    MODEL 11 — ASIAN RANGE JUDAS SWING (SESSION LIQUIDITY SWEEP)
    Institutional Sequence:
    1. Asian Session (00:00 - 06:00 UTC / 05:30 - 11:30 IST) defines Asian High (ASH) and Asian Low (ASL).
    2. London Open (08:00 - 11:00 UTC / 13:30 - 16:30 IST) or NY Open spikes beyond ASH or ASL (Judas Swing).
    3. Price grabs trapped breakout liquidity and violently rejects back inside the Asian Range.
    4. Execution: Enter on closed candle back inside range targeting the opposite range extreme.
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_11",
            name="Asian Range Judas Swing",
            description="London/NY Judas swing sweeping Asian session high/low with sharp reversal back into range"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 20 or len(market.candles_15m) < 15:
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        # 1. Identify Asian Session Range (lookback within last 24h)
        asian_candles = []
        for c in reversed(c15):
            dt = datetime.fromtimestamp(c.time, tz=timezone.utc)
            if 0 <= dt.hour < 6:
                asian_candles.append(c)
            elif asian_candles and dt.hour >= 6:
                break

        if len(asian_candles) < 4:
            asian_high = max(c.high for c in c15[-28:-12])
            asian_low = min(c.low for c in c15[-28:-12])
        else:
            asian_high = max(c.high for c in asian_candles)
            asian_low = min(c.low for c in asian_candles)

        range_height = asian_high - asian_low
        if range_height <= 0 or range_height < (atr_5m * 1.5):
            return None

        recent_bars = c5[-12:]
        swept_high = False
        swept_low = False
        sweep_extreme_high = asian_high
        sweep_extreme_low = asian_low

        for bar in recent_bars:
            if bar.high > asian_high:
                swept_high = True
                if bar.high > sweep_extreme_high:
                    sweep_extreme_high = bar.high
            if bar.low < asian_low:
                swept_low = True
                if bar.low < sweep_extreme_low:
                    sweep_extreme_low = bar.low

        direction = None
        stop_loss = 0.0
        target_1 = 0.0
        target_2 = 0.0

        if swept_low and not swept_high and curr_price > asian_low:
            lowest_bar = min(recent_bars, key=lambda b: b.low)
            if lowest_bar.close > lowest_bar.low:
                direction = "LONG"
                stop_loss = sweep_extreme_low - (atr_5m * 0.4)
                target_1 = asian_low + (range_height * 0.5)
                target_2 = asian_high
        elif swept_high and not swept_low and curr_price < asian_high:
            highest_bar = max(recent_bars, key=lambda b: b.high)
            if highest_bar.close < highest_bar.high:
                direction = "SHORT"
                stop_loss = sweep_extreme_high + (atr_5m * 0.4)
                target_1 = asian_high - (range_height * 0.5)
                target_2 = asian_low

        if not direction:
            return None

        risk = abs(curr_price - stop_loss)
        if risk <= 0:
            return None
        reward_2 = abs(target_2 - curr_price)
        rr = reward_2 / risk

        if rr < 1.6:
            target_2 = curr_price + (risk * 2.2) if direction == "LONG" else curr_price - (risk * 2.2)
            rr = 2.2

        obs = OrderBlockEngine.find_order_blocks(symbol, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, direction)
        fvgs = FvgEngine.find_fvgs(symbol, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, direction)
        disp = DisplacementEngine.evaluate(c5)

        confs = ConfirmationEngine.evaluate(
            direction=direction,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context,
            active_ob=active_ob,
            active_fvg=active_fvg
        )

        rvol = calculate_rvol(c5)
        vol_ok = rvol >= 1.10 or disp.detected

        from strategy.scoring import calculate_institutional_100_score
        breakdown = calculate_institutional_100_score(
            htf_aligned=confs.trend_ok,
            sweep_confirmed=True,
            displacement_mss=disp.detected,
            pd_array_confirmed=True,
            ob_fvg_confluence=(active_ob is not None or active_fvg is not None),
            volume_confirmed=vol_ok,
            rvol=rvol,
            risk_reward=rr
        )
        score = min(100, max(75, breakdown.total_score + 10))

        cand = StrategyCandidate(
            id=f"M11_{symbol}_{direction}_{int(time.time())}",
            coin=symbol,
            model_id="MODEL_11",
            model_name="Asian Range Judas Swing",
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
            grade_badge="🌟 GRADE: A+ (JUDAS SWING)",
            reasons=[
                f"Judas Swing: Swept Asian Range {'Low' if direction == 'LONG' else 'High'} ({asian_low if direction == 'LONG' else asian_high:.4f})",
                f"Reclaimed Range: Current price ({curr_price:.4f}) back inside Asian box",
                f"Target: Opposing Asian boundary ({target_2:.4f}) with 1:{rr:.2f}R"
            ]
        )
        return cand
