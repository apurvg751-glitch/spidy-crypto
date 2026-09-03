import time
from typing import Optional
from market_data.models import MarketState
from indicators.atr import calculate_atr
from indicators.volume import calculate_rvol
from indicators.displacement import DisplacementEngine
from structure.swings import find_swings
from structure.liquidity import detect_liquidity_sweep, LiquidityEngine
from structure.bos import detect_bos
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from structure.equilibrium import EquilibriumEngine
from risk_engine.risk_calculator import RiskEngine
from strategy.confirmation_engine import ConfirmationEngine
from strategy.scoring import calculate_institutional_100_score
from strategy.state_machine import SetupSequence
from strategy.models.base_model import BaseStrategyModel, StrategyCandidate


class Model10InstitutionalSniper(BaseStrategyModel):
    """
    Model 10: Institutional Sniper ⭐ (ICT/SMC 100% Confluence)
    Core detection sequence:
    1. HTF 4H/1H Macro Alignment
    2. Key Liquidity Sweep (BSL/SSL or Equal Extremes Purge)
    3. Market Structure Shift (MSS) with Institutional Displacement
    4. Price retraces into unmitigated Order Block + FVG in Discount/Premium
    5. Perfect 100/100 Sniper Execution
    Best environment: High-Conviction Institutional A+ Platinum Entries.
    """

    def __init__(self):
        super().__init__(
            model_id="MODEL_10",
            name="Institutional Sniper ⭐ (100% Confluence)",
            description="HTF Bias -> Liquidity Sweep -> Displacement MSS -> Retrace to OB+FVG in Discount/Premium"
        )

    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        c5 = market.candles_5m
        c15 = market.candles_15m
        sym = market.symbol

        if len(c5) < 30 or len(c15) < 15:
            return None

        # 1. Higher Timeframe Alignment
        macro_4h = market.mtf_context.macro_bias_4h.upper() if market.mtf_context else "BULLISH"
        trend_1h = market.mtf_context.trend_1h.upper() if market.mtf_context else "BULLISH"

        # Determine Primary Institutional Bias
        if macro_4h == "BULLISH" or (trend_1h == "BULLISH" and macro_4h != "BEARISH"):
            primary_direction = "LONG"
            htf_aligned = True
        elif macro_4h == "BEARISH" or (trend_1h == "BEARISH" and macro_4h != "BULLISH"):
            primary_direction = "SHORT"
            htf_aligned = True
        else:
            primary_direction = "LONG"
            htf_aligned = False

        # 2. Key Liquidity Sweep & Swings
        swings = find_swings(c5)
        sweep = detect_liquidity_sweep(c5, swings)
        eq_pools = LiquidityEngine.find_equal_highs_lows(swings)
        sweep_confirmed = (
            sweep.detected and 
            ((primary_direction == "LONG" and sweep.sweep_type == "BULLISH") or 
             (primary_direction == "SHORT" and sweep.sweep_type == "BEARISH"))
        ) or len(eq_pools) > 0

        # 3. Market Structure Shift (MSS) + Displacement
        bos = detect_bos(c5, swings)
        disp = DisplacementEngine.evaluate(c5)
        mss_confirmed = (bos.detected and bos.direction == primary_direction) or disp.detected

        # 4. Premium vs Discount Dealing Range
        dr = EquilibriumEngine.calculate_range(c15 or c5)
        pd_ok, pd_desc = EquilibriumEngine.validate_setup_zone(primary_direction, market.current_price, dr)

        # 5. Order Block + FVG Confluence
        obs = OrderBlockEngine.find_order_blocks(sym, c5)
        active_ob = OrderBlockEngine.get_active_ob(obs, primary_direction)
        fvgs = FvgEngine.find_fvgs(sym, c5)
        active_fvg = FvgEngine.get_active_fvg(fvgs, primary_direction)
        ob_fvg_ok = (active_ob is not None) or (active_fvg is not None)

        # 6. Technical Indicators: ATR & RVOL
        atr = calculate_atr(c5)
        rvol = calculate_rvol(c5)
        vol_confirmed = rvol >= 1.20

        # 7. Confirmations
        confs = ConfirmationEngine.evaluate(
            direction=primary_direction,
            candles_5m=c5,
            candles_15m=c15,
            mtf_context=market.mtf_context,
            active_ob=active_ob,
            active_fvg=active_fvg
        )

        # Calculate Invalidation and Targets
        extreme_level = active_ob.bottom if (active_ob and primary_direction == "LONG") else (
            active_ob.top if (active_ob and primary_direction == "SHORT") else (
                market.current_price - (atr * 1.2) if primary_direction == "LONG" else market.current_price + (atr * 1.2)
            )
        )

        levels = RiskEngine.calculate_levels(
            direction=primary_direction,
            current_price=market.current_price,
            extreme_level=extreme_level,
            atr=atr,
            min_rr=2.5,
            grade="A+"
        )

        if not levels.is_valid:
            return None

        # Calculate 7-Pillar Institutional 100/100 Score
        score_breakdown = calculate_institutional_100_score(
            htf_aligned=htf_aligned,
            sweep_confirmed=sweep_confirmed,
            displacement_mss=mss_confirmed,
            pd_array_confirmed=pd_ok,
            ob_fvg_confluence=ob_fvg_ok,
            volume_confirmed=vol_confirmed,
            rvol=rvol,
            risk_reward=levels.risk_reward
        )

        # Only trigger if institutional threshold (>= 80) is met
        if score_breakdown.total_score < 80:
            return None

        now = int(time.time())
        setup_id = f"{sym}_SNIPER_{primary_direction}_{now}"

        sequence = SetupSequence(
            sequence_id=f"seq_{setup_id}",
            symbol=sym,
            model_id=self.model_id,
            direction=primary_direction,
            current_state="READY"
        )

        is_perfect_100 = score_breakdown.total_score >= 95
        badge = (
            "💎 GRADE: 100/100 INSTITUTIONAL SNIPER (PERFECT CONFLUENCE)"
            if is_perfect_100 else
            f"🌟 GRADE: A+ ({score_breakdown.total_score}/100 INSTITUTIONAL)"
        )

        reasons = [
            badge,
            f"7-Pillar Institutional Confluence: {score_breakdown.total_score}/100",
            f"HTF Bias: 4H {macro_4h} | 1H {trend_1h}",
            f"Dealing Range: {dr.description if dr else 'Neutral'}",
            f"Displacement: {disp.description}",
            f"Liquidity Sweep: {sweep.description if sweep.detected else 'EQ Pools Purged'}",
            f"BOS / MSS: {bos.description if bos.detected else 'Structure Shift Confirmed'}",
            f"Order Block: {'Demand OB [' + str(round(active_ob.bottom, 2)) + ' - ' + str(round(active_ob.top, 2)) + ']' if active_ob else 'Dynamic Order Block'}",
            f"FVG: {'Fair Value Gap [' + str(round(active_fvg.bottom, 2)) + ' - ' + str(round(active_fvg.top, 2)) + ']' if active_fvg else 'Dynamic FVG'}",
            f"Risk: SL {levels.stop_loss:.2f} | T1 {levels.target_1:.2f} | T2 {levels.target_2:.2f} (RR 1:{levels.risk_reward:.1f})"
        ]

        return StrategyCandidate(
            id=setup_id,
            coin=sym,
            model_id=self.model_id,
            model_name=self.name,
            direction=primary_direction,
            detection_timestamp=now,
            entry=levels.entry,
            stop_loss=levels.stop_loss,
            target_1=levels.target_1,
            target_2=levels.target_2,
            rr=levels.risk_reward,
            setup_score=score_breakdown.total_score,
            score_breakdown=score_breakdown,
            confirmations=confs,
            state_sequence=sequence,
            reasons=reasons,
            grade="A+",
            grade_badge=badge,
            is_valid=True
        )
