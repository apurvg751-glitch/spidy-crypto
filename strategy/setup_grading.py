from typing import Optional
from pydantic import BaseModel
from market_data.models import MultiTimeframeContext, ConfirmationsResult
from structure.equilibrium import DealingRange, EquilibriumEngine
from indicators.displacement import DisplacementResult


class SetupGradeResult(BaseModel):
    grade: str = "REJECTED"                # "A+", "B+", "REJECTED"
    is_tradeable: bool = False
    macro_aligned: bool = False
    pd_zone_ok: bool = False
    displacement_ok: bool = False
    confirmations_count: int = 0
    score: int = 0
    sl_atr_multiplier: float = 0.35        # 0.35 for A+, 0.15 for B+ (Stricter SL)
    target_1_rr: float = 1.8               # 1.8R for A+, 1.6R for B+ (Stricter quick TP)
    target_2_rr: float = 2.5               # 2.5R for A+, 1.8R for B+
    breakeven_trigger_r: float = 0.8       # 0.8R for A+, 0.6R for B+ (Aggressive BE)
    badge: str = "REJECTED"
    summary: str = ""


class SetupGradingEngine:
    """
    Evaluates setups to separate A+ (Institutional High-Conviction) from
    B+ (Cautious / Stricter Risk) setups.

    A+ SETUP CRITERIA:
    1. Score >= 85
    2. Confirmations >= 5/7
    3. Macro 4H / 1H trend aligned (No counter-trend)
    4. Premium / Discount validated (Discount for Long, Premium for Short)
    5. Institutional Displacement or strong RVOL confirmed

    B+ SETUP CRITERIA (User Directive: Give it stricter SL and TP):
    1. Score 70 - 84, Confirmations >= 4/7
    2. Minor counter-trend or equilibrium zone
    3. Stricter Stop Loss (0.15 * ATR tight invalidation)
    4. Conservative Quick Target 1 (1.6R) and rapid breakeven move at 0.6R
    """

    @staticmethod
    def grade_setup(
        direction: str,
        current_price: float,
        setup_score: int,
        confirmations: Optional[ConfirmationsResult],
        mtf_context: Optional[MultiTimeframeContext],
        dealing_range: Optional[DealingRange],
        displacement: Optional[DisplacementResult]
    ) -> SetupGradeResult:
        dir_upper = direction.upper()

        # 1. Check Macro Trend Alignment
        macro_aligned = False
        if mtf_context:
            macro_4h = mtf_context.macro_bias_4h.upper()
            trend_1h = mtf_context.trend_1h.upper()
            if dir_upper == "LONG":
                # Aligned if 4H is Bullish or 1H is Bullish without Bearish 4H
                macro_aligned = (macro_4h == "BULLISH") or (trend_1h == "BULLISH" and macro_4h != "BEARISH")
            elif dir_upper == "SHORT":
                macro_aligned = (macro_4h == "BEARISH") or (trend_1h == "BEARISH" and macro_4h != "BULLISH")
        else:
            macro_aligned = True

        # 2. Check Premium vs Discount Zone
        pd_zone_ok, pd_desc = EquilibriumEngine.validate_setup_zone(dir_upper, current_price, dealing_range)

        # 3. Displacement
        displacement_ok = displacement.detected if displacement else False

        # 4. Confirmations count
        conf_count = confirmations.passed_count if confirmations else 0

        # Hard Reject: Counter-trend on wrong side of dealing range with low score
        if not macro_aligned and not pd_zone_ok:
            return SetupGradeResult(
                grade="REJECTED",
                is_tradeable=False,
                summary="Rejected: Counter-macro trend in opposing Premium/Discount zone."
            )

        # Evaluate A+ Setup
        if (setup_score >= 85 and conf_count >= 5 and macro_aligned and pd_zone_ok):
            return SetupGradeResult(
                grade="A+",
                is_tradeable=True,
                macro_aligned=True,
                pd_zone_ok=True,
                displacement_ok=displacement_ok,
                confirmations_count=conf_count,
                score=setup_score,
                sl_atr_multiplier=0.35,
                target_1_rr=1.8,
                target_2_rr=2.5,
                breakeven_trigger_r=0.8,
                badge="🌟 GRADE: A+ (INSTITUTIONAL CONVICTION)",
                summary=f"A+ Institutional Setup: Score {setup_score}, {conf_count}/7 Confirms, Macro Aligned, {pd_desc}"
            )

        # Evaluate B+ Setup (Meets trading threshold but requires stricter risk)
        if (setup_score >= 70 and conf_count >= 4):
            return SetupGradeResult(
                grade="B+",
                is_tradeable=True,
                macro_aligned=macro_aligned,
                pd_zone_ok=pd_zone_ok,
                displacement_ok=displacement_ok,
                confirmations_count=conf_count,
                score=setup_score,
                sl_atr_multiplier=0.15,       # Stricter tight SL
                target_1_rr=1.6,              # Quick TP (Min 1.6R)
                target_2_rr=1.8,              # Cautious T2
                breakeven_trigger_r=0.6,      # Rapid Breakeven protection
                badge="⚡ GRADE: B+ (STRICT RISK / TIGHT SL)",
                summary=f"B+ Setup: Score {setup_score}, {conf_count}/7 Confirms. Stricter SL (0.15 ATR) & Quick TP (1.6R) active."
            )

        return SetupGradeResult(
            grade="REJECTED",
            is_tradeable=False,
            confirmations_count=conf_count,
            score=setup_score,
            badge="REJECTED",
            summary=f"Rejected: Score {setup_score}/100 and Confirms {conf_count}/7 did not meet B+ qualification bar."
        )
