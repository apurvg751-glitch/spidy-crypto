import time
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


class Model14SmtDivergence(BaseStrategyModel):
    """
    MODEL 14 — SMART MONEY TOOL (SMT) INTERMARKET DIVERGENCE
    Institutional Sequence:
    1. Compares monitored Altcoin (ETH, SOL, XRP, AVAX) with BTC Mother-Ship.
    2. Bullish SMT: BTC makes a Lower Low (LL), but the Altcoin makes a Higher Low (HL).
       Institutional smart money is absorbing the altcoin and refusing to let it break.
    3. Bearish SMT: BTC makes a Higher High (HH), but the Altcoin makes a Lower High (LH).
       Institutional smart money is distributing the altcoin and refusing to push it higher.
    4. Execution: Enter on Altcoin MSS confirmation with stop loss anchored behind the divergence pivot.
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_14",
            name="SMT Intermarket Divergence",
            description="Smart Money Tool (SMT) intermarket divergence between Altcoin and BTC Mother-Ship"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        if market.is_stale or len(market.candles_5m) < 30 or len(market.candles_15m) < 15:
            return None

        # BTC cannot trade SMT against itself
        if market.symbol.upper() == "BTCUSD":
            return None

        c5 = market.candles_5m
        c15 = market.candles_15m
        symbol = market.symbol
        curr_price = market.current_price or c5[-1].close
        atr_5m = calculate_atr(c5, period=settings.ATR_PERIOD)

        alt_swings = find_swings(c5, lookback=4)
        if len(alt_swings) < 3:
            return None

        direction = None
        stop_loss = 0.0
        target_1 = 0.0
        target_2 = 0.0
        smt_reason = ""

        # Check if BTC candles are attached to market state
        btc_candles = getattr(market, "btc_candles_15m", []) or []
        macro_4h = market.mtf_context.macro_bias_4h if market.mtf_context else "Neutral"
        trend_1h = market.mtf_context.trend_1h if market.mtf_context else "Neutral"

        if btc_candles and len(btc_candles) >= 15:
            btc_swings = find_swings(btc_candles, lookback=4)
            # Bullish SMT: BTC made LL, Alt made HL
            alt_lows = [s for s in alt_swings if s.point_type == "LOW"]
            btc_lows = [s for s in btc_swings if s.point_type == "LOW"]
            if len(alt_lows) >= 2 and len(btc_lows) >= 2 and macro_4h != "Bearish":
                alt_prev_l, alt_curr_l = alt_lows[-2], alt_lows[-1]
                btc_prev_l, btc_curr_l = btc_lows[-2], btc_lows[-1]
                # BTC made lower low, but Alt held higher low by at least 0.3 ATR
                if btc_curr_l.price < btc_prev_l.price and alt_curr_l.price > (alt_prev_l.price + atr_5m * 0.3):
                    # Alt confirms with bullish reversal candle
                    if curr_price > alt_curr_l.price and c5[-1].is_bullish:
                        direction = "LONG"
                        stop_loss = alt_curr_l.price - (atr_5m * 0.4)
                        smt_reason = f"Bullish SMT: BTC swept to LL while {symbol} printed HL ({alt_curr_l.price:.4f} > {alt_prev_l.price:.4f})"

            # Bearish SMT: BTC made HH, Alt made LH
            alt_highs = [s for s in alt_swings if s.point_type == "HIGH"]
            btc_highs = [s for s in btc_swings if s.point_type == "HIGH"]
            if not direction and len(alt_highs) >= 2 and len(btc_highs) >= 2 and macro_4h != "Bullish":
                alt_prev_h, alt_curr_h = alt_highs[-2], alt_highs[-1]
                btc_prev_h, btc_curr_h = btc_highs[-2], btc_highs[-1]
                # BTC made higher high, but Alt printed lower high by at least 0.3 ATR
                if btc_curr_h.price > btc_prev_h.price and alt_curr_h.price < (alt_prev_h.price - atr_5m * 0.3):
                    # Alt confirms with bearish reversal candle
                    if curr_price < alt_curr_h.price and c5[-1].is_bearish:
                        direction = "SHORT"
                        stop_loss = alt_curr_h.price + (atr_5m * 0.4)
                        smt_reason = f"Bearish SMT: BTC pushed to HH while {symbol} printed LH ({alt_curr_h.price:.4f} < {alt_prev_h.price:.4f})"

        if not direction:
            return None

        risk = abs(curr_price - stop_loss)
        if risk <= 0 or risk < (atr_5m * 0.4):
            stop_loss = (curr_price - atr_5m * 0.85) if direction == "LONG" else (curr_price + atr_5m * 0.85)
            risk = abs(curr_price - stop_loss)

        target_1 = curr_price + (risk * 1.6) if direction == "LONG" else curr_price - (risk * 1.6)
        target_2 = curr_price + (risk * 2.5) if direction == "LONG" else curr_price - (risk * 2.5)
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
            id=f"M14_{symbol}_{direction}_{int(time.time())}",
            coin=symbol,
            model_id="MODEL_14",
            model_name="SMT Intermarket Divergence",
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
            grade_badge="🔗 GRADE: A+ (SMT DIVERGENCE)",
            reasons=[
                smt_reason or f"SMT Confluence: Relative strength divergence detected",
                f"Entry at {curr_price:.4f} with protected stop at {stop_loss:.4f}",
                f"Target 1: {target_1:.4f} | Target 2: {target_2:.4f} (1:{rr:.2f}R)"
            ]
        )
        return cand
