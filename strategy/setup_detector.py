import logging
import time
from typing import Literal, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("spidy.strategy.detector")

from config.settings import settings
from market_data.models import Candle
from indicators.atr import calculate_atr
from indicators.volume import calculate_rvol, is_volume_confirmed
from indicators.moving_averages import get_trend_bias
from structure.swings import find_swings
from structure.liquidity import detect_liquidity_sweep
from structure.bos import detect_bos
from risk_engine.risk_calculator import RiskEngine
from .scoring import calculate_setup_score, SetupScoreBreakdown


class DetectedSetup(BaseModel):
    id: str
    coin: str
    direction: Literal["LONG", "SHORT"]
    detection_timestamp: int
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    rr: float
    setup_score: int
    score_breakdown: SetupScoreBreakdown
    trend_15m: str
    sweep_confirmed: bool
    sweep_details: str
    bos_confirmed: bool
    bos_details: str
    volume_confirmed: bool
    atr: float
    reasons: list[str] = Field(default_factory=list)
    dom_imbalance: Optional[str] = None
    dom_wall: Optional[str] = None
    funding_rate_pct: Optional[float] = None
    liquidation_target: Optional[float] = None


class SetupEvaluationResult(BaseModel):
    symbol: str
    signal: Literal["LONG", "SHORT", "NO SETUP"]
    setup: Optional[DetectedSetup] = None
    rejection_reasons: list[str] = Field(default_factory=list)


class SetupDetector:
    """
    Deterministic setup detection engine for SPIDY CRYPTO.
    Uses 15m timeframe for HTF trend and 5m timeframe for execution triggers.
    Does NOT use an LLM directly for buy/sell determinations.
    """

    @staticmethod
    def evaluate(
        symbol: str,
        candles_5m: list[Candle],
        candles_15m: list[Candle],
        current_price: float,
        is_stale: bool = False
    ) -> SetupEvaluationResult:
        rejection_reasons: list[str] = []

        # 1. Stale / Completeness Guard
        if is_stale:
            return SetupEvaluationResult(
                symbol=symbol,
                signal="NO SETUP",
                rejection_reasons=["Market data is marked stale or disconnected"]
            )

        if len(candles_5m) < 20 or len(candles_15m) < 15:
            return SetupEvaluationResult(
                symbol=symbol,
                signal="NO SETUP",
                rejection_reasons=[f"Insufficient candle history (5m: {len(candles_5m)}, 15m: {len(candles_15m)})"]
            )

        # 2. Higher Timeframe (15m) Trend
        trend_15m = get_trend_bias(candles_15m)

        # 3. 5m Technical Structure
        swings_5m = find_swings(candles_5m, lookback=settings.SWING_LOOKBACK)
        sweep_5m = detect_liquidity_sweep(candles_5m, swings_5m, search_bars=8)
        bos_5m = detect_bos(candles_5m, swings_5m, search_bars=8)

        # 4. Indicators: ATR & Volume
        atr_5m = calculate_atr(candles_5m, period=settings.ATR_PERIOD)
        rvol = calculate_rvol(candles_5m, period=20)
        vol_confirmed = is_volume_confirmed(candles_5m, period=20, threshold=1.10)

        latest_candle = candles_5m[-1]

        # -------------------------------------------------------------
        # EVALUATE LONG SETUP
        # -------------------------------------------------------------
        bullish_trigger = (
            (sweep_5m.detected and sweep_5m.sweep_type == "BULLISH") or
            (bos_5m.detected and bos_5m.direction == "BULLISH")
        )

        if bullish_trigger and trend_15m in ("Bullish", "Neutral"):
            # Check rejection candle (lower wick rejection or strong close)
            rejection_confirmed = (
                latest_candle.lower_wick >= (latest_candle.total_range * 0.25) or
                latest_candle.is_bullish
            )

            # Determine structural low for stop loss
            extreme_low = sweep_5m.extreme_price if sweep_5m.detected else (
                min(c.low for c in candles_5m[-5:])
            )

            # Calculate risk levels
            levels = RiskEngine.calculate_levels(
                direction="LONG",
                current_price=current_price or latest_candle.close,
                extreme_level=extreme_low,
                atr=atr_5m,
                min_rr=settings.MIN_RISK_REWARD
            )

            if levels.is_valid:
                # Calculate deterministic setup score
                score_breakdown = calculate_setup_score(
                    trend_aligned=(trend_15m == "Bullish"),
                    trend_neutral=(trend_15m == "Neutral"),
                    sweep_confirmed=(sweep_5m.detected and sweep_5m.sweep_type == "BULLISH"),
                    bos_confirmed=(bos_5m.detected and bos_5m.direction == "BULLISH"),
                    volume_confirmed=vol_confirmed,
                    rvol=rvol,
                    risk_reward=levels.risk_reward
                )

                reasons = [
                    f"15M Trend: {trend_15m}",
                    f"Liquidity Sweep: {'Confirmed (' + sweep_5m.description + ')' if sweep_5m.detected else 'None'}",
                    f"BOS: {'Confirmed (' + bos_5m.description + ')' if bos_5m.detected else 'None'}",
                    f"Volume RVOL: {rvol:.2f} ({'Confirmed' if vol_confirmed else 'Moderate'})",
                    f"Rejection: {'Confirmed' if rejection_confirmed else 'Standard'}",
                    f"Setup Score: {score_breakdown.total_score}/100"
                ]

                if score_breakdown.total_score >= settings.MIN_SETUP_SCORE:
                    det_ts = latest_candle.time or int(time.time())
                    setup_id = f"{symbol}_LONG_{det_ts}_{int(levels.entry)}"
                    setup = DetectedSetup(
                        id=setup_id,
                        coin=symbol,
                        direction="LONG",
                        detection_timestamp=det_ts,
                        entry=levels.entry,
                        stop_loss=levels.stop_loss,
                        target_1=levels.target_1,
                        target_2=levels.target_2,
                        rr=levels.risk_reward,
                        setup_score=score_breakdown.total_score,
                        score_breakdown=score_breakdown,
                        trend_15m=trend_15m,
                        sweep_confirmed=(sweep_5m.detected and sweep_5m.sweep_type == "BULLISH"),
                        sweep_details=sweep_5m.description if sweep_5m.detected else "None",
                        bos_confirmed=(bos_5m.detected and bos_5m.direction == "BULLISH"),
                        bos_details=bos_5m.description if bos_5m.detected else "None",
                        volume_confirmed=vol_confirmed,
                        volume_details=f"RVOL {rvol:.2f}",
                        atr=round(atr_5m, 4),
                        reasons=reasons
                    )
                    return SetupEvaluationResult(symbol=symbol, signal="LONG", setup=setup)
                else:
                    rejection_reasons.append(f"LONG score {score_breakdown.total_score} below threshold {settings.MIN_SETUP_SCORE}")
            else:
                rejection_reasons.append(f"LONG risk levels invalid: {levels.rejection_reason}")

        # -------------------------------------------------------------
        # EVALUATE SHORT SETUP
        # -------------------------------------------------------------
        bearish_trigger = (
            (sweep_5m.detected and sweep_5m.sweep_type == "BEARISH") or
            (bos_5m.detected and bos_5m.direction == "BEARISH")
        )

        if bearish_trigger and trend_15m in ("Bearish", "Neutral"):
            # Check rejection candle (upper wick rejection or strong close)
            rejection_confirmed = (
                latest_candle.upper_wick >= (latest_candle.total_range * 0.25) or
                latest_candle.is_bearish
            )

            extreme_high = sweep_5m.extreme_price if sweep_5m.detected else (
                max(c.high for c in candles_5m[-5:])
            )

            levels = RiskEngine.calculate_levels(
                direction="SHORT",
                current_price=current_price or latest_candle.close,
                extreme_level=extreme_high,
                atr=atr_5m,
                min_rr=settings.MIN_RISK_REWARD
            )

            if levels.is_valid:
                score_breakdown = calculate_setup_score(
                    trend_aligned=(trend_15m == "Bearish"),
                    trend_neutral=(trend_15m == "Neutral"),
                    sweep_confirmed=(sweep_5m.detected and sweep_5m.sweep_type == "BEARISH"),
                    bos_confirmed=(bos_5m.detected and bos_5m.direction == "BEARISH"),
                    volume_confirmed=vol_confirmed,
                    rvol=rvol,
                    risk_reward=levels.risk_reward
                )

                reasons = [
                    f"15M Trend: {trend_15m}",
                    f"Liquidity Sweep: {'Confirmed (' + sweep_5m.description + ')' if sweep_5m.detected else 'None'}",
                    f"BOS: {'Confirmed (' + bos_5m.description + ')' if bos_5m.detected else 'None'}",
                    f"Volume RVOL: {rvol:.2f} ({'Confirmed' if vol_confirmed else 'Moderate'})",
                    f"Rejection: {'Confirmed' if rejection_confirmed else 'Standard'}",
                    f"Setup Score: {score_breakdown.total_score}/100"
                ]

                if score_breakdown.total_score >= settings.MIN_SETUP_SCORE:
                    det_ts = latest_candle.time or int(time.time())
                    setup_id = f"{symbol}_SHORT_{det_ts}_{int(levels.entry)}"
                    setup = DetectedSetup(
                        id=setup_id,
                        coin=symbol,
                        direction="SHORT",
                        detection_timestamp=det_ts,
                        entry=levels.entry,
                        stop_loss=levels.stop_loss,
                        target_1=levels.target_1,
                        target_2=levels.target_2,
                        rr=levels.risk_reward,
                        setup_score=score_breakdown.total_score,
                        score_breakdown=score_breakdown,
                        trend_15m=trend_15m,
                        sweep_confirmed=(sweep_5m.detected and sweep_5m.sweep_type == "BEARISH"),
                        sweep_details=sweep_5m.description if sweep_5m.detected else "None",
                        bos_confirmed=(bos_5m.detected and bos_5m.direction == "BEARISH"),
                        bos_details=bos_5m.description if bos_5m.detected else "None",
                        volume_confirmed=vol_confirmed,
                        volume_details=f"RVOL {rvol:.2f}",
                        atr=round(atr_5m, 4),
                        reasons=reasons
                    )
                    return SetupEvaluationResult(symbol=symbol, signal="SHORT", setup=setup)
                else:
                    rejection_reasons.append(f"SHORT score {score_breakdown.total_score} below threshold {settings.MIN_SETUP_SCORE}")
            else:
                rejection_reasons.append(f"SHORT risk levels invalid: {levels.rejection_reason}")

        if not rejection_reasons:
            rejection_reasons.append("No valid sweep, BOS, or trend alignment found on 5m/15m")

        return SetupEvaluationResult(
            symbol=symbol,
            signal="NO SETUP",
            rejection_reasons=rejection_reasons
        )

    @classmethod
    def evaluate_all_models(cls, market) -> list:
        """
        Runs all 6 independent strategy models on the given market state.
        Returns all valid qualified candidates (score >= 70, confirmations >= 4/7).
        """
        from strategy.models import (
            Model1SweepReversal,
            Model2BosContinuation,
            Model3ObFvg,
            Model4ChochReversal,
            Model5BreakoutRetest,
            Model6TrendPullback,
            Model8ObFvgPullback,
            Model9LiquiditySweepReversal,
            Model10InstitutionalSniper
        )

        models = [
            Model1SweepReversal(),
            Model2BosContinuation(),
            Model3ObFvg(),
            Model4ChochReversal(),
            Model5BreakoutRetest(),
            Model6TrendPullback(),
            Model8ObFvgPullback(),
            Model9LiquiditySweepReversal(),
            Model10InstitutionalSniper()
        ]

        from structure.equilibrium import EquilibriumEngine
        from indicators.displacement import DisplacementEngine
        from structure.barrier_engine import BarrierEngine
        from strategy.setup_grading import SetupGradingEngine
        from structure.target_snapper import TargetSnapper
        from structure.kill_zones import KillZoneEngine
        from structure.session_vwap import SessionVWAPEngine
        from strategy.reentry_manager import ReentryManager

        # Use 100% completed, closed candles (eliminate mid-candle tick fluctuations)
        c5 = market.candles_5m
        c15 = market.candles_15m
        closed_5m = c5[:-1] if len(c5) > 1 else c5
        closed_15m = c15[:-1] if len(c15) > 1 else c15
        ref_price = closed_5m[-1].close if closed_5m else market.current_price

        closed_market = market.model_copy(update={
            "candles_5m": closed_5m,
            "candles_15m": closed_15m,
            "current_price": ref_price
        })

        # Compute current Dealing Range, Displacement, Kill Zone, and Session VWAP
        dr = EquilibriumEngine.calculate_range(closed_15m or closed_5m)
        disp = DisplacementEngine.evaluate(closed_5m)
        kz = KillZoneEngine.evaluate(closed_15m)
        vwap_res = SessionVWAPEngine.calculate(closed_5m, ref_price)

        candidates = []
        for m in models:
            cand = m.evaluate(closed_market)
            if cand and cand.is_valid:
                # Validate Structural Ceiling/Floor Barrier & Room to Run
                barrier_res = BarrierEngine.validate_room_to_run(
                    direction=cand.direction,
                    current_price=cand.entry,
                    candles_15m=closed_15m,
                    atr=cand.score_breakdown.atr_value if hasattr(cand.score_breakdown, "atr_value") else (cand.entry * 0.005),
                    dealing_range=dr
                )

                # Grade Setup: A+ vs B+
                grade_res = SetupGradingEngine.grade_setup(
                    direction=cand.direction,
                    current_price=cand.entry,
                    setup_score=int(cand.setup_score * kz.confidence_multiplier) if kz.is_active_kill_zone else cand.setup_score,
                    confirmations=cand.confirmations,
                    mtf_context=market.mtf_context,
                    dealing_range=dr,
                    displacement=disp
                )

                if not grade_res.is_tradeable:
                    continue

                cand.grade = grade_res.grade
                cand.grade_badge = grade_res.badge

                cand_atr = cand.score_breakdown.atr_value if hasattr(cand.score_breakdown, "atr_value") else (cand.entry * 0.005)

                # Ensure minimum stop loss distance floor (prevent paper-thin stops)
                min_risk = max(cand_atr * 0.60, cand.entry * 0.0035)
                current_risk = abs(cand.entry - cand.stop_loss)
                if current_risk < min_risk:
                    cand.stop_loss = round((cand.entry - min_risk) if cand.direction == "LONG" else (cand.entry + min_risk), 2)

                # Snap targets to real physical swing structure (Draw on Liquidity)
                snapped = TargetSnapper.snap_targets(
                    direction=cand.direction,
                    entry=cand.entry,
                    stop_loss=cand.stop_loss,
                    candles_15m=closed_15m,
                    dealing_range=dr,
                    atr=cand_atr,
                    min_rr=1.6
                )

                # HARD REJECTION GATE: TP1 MUST provide at least 1.6R clearance
                if not snapped.has_minimum_clearance or snapped.rr_1 < 1.6:
                    logger.info(f"Setup {cand.id} REJECTED: TP1 ({snapped.target_1}) too close to entry ({cand.entry}) | RR1: {snapped.rr_1:.2f} < 1.6R")
                    continue

                # RE-ENTRY & COOLDOWN GATE: Enforce fresh structure and prevent price chasing
                reentry_mgr = ReentryManager()
                reentry_ok, reentry_reason, overext_ratio = reentry_mgr.evaluate_candidate(
                    candidate=cand,
                    candles_5m=closed_5m,
                    atr=cand_atr
                )
                if not reentry_ok:
                    logger.info(f"Setup {cand.id} ({cand.coin}) REJECTED by Re-entry Gate: {reentry_reason}")
                    continue

                cand.target_1 = snapped.target_1
                cand.target_2 = snapped.target_2
                cand.rr = snapped.rr_2

                # Prepend Grade badge and append qualification summaries
                cand.reasons.insert(0, grade_res.badge)
                cand.reasons.append(barrier_res.reason)
                cand.reasons.append(snapped.description)
                cand.reasons.append(f"Session Timing: {kz.description}")
                if vwap_res:
                    cand.reasons.append(f"Value Area: {vwap_res.description}")
                cand.reasons.append(f"Re-Entry Safety: Verified Fresh Structure (Overextension: {overext_ratio}x ATR)")
                cand.reasons.append(grade_res.summary)
                candidates.append(cand)

        return candidates

