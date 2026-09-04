from typing import Optional
from pydantic import BaseModel
from market_data.models import MultiTimeframeContext, ConfirmationsResult
from market_data.l2_book import OrderBookAnalysis
from market_data.derivatives_intel import DerivativesIntel
from structure.equilibrium import DealingRange, EquilibriumEngine
from indicators.displacement import DisplacementResult


class SetupGradeResult(BaseModel):
    grade: str = "REJECTED"                # "A+", "B+", "REJECTED"
    is_tradeable: bool = False
    macro_aligned: bool = False
    pd_zone_ok: bool = False
    displacement_ok: bool = False
    dom_confluence: bool = False
    liquidation_confluence: bool = False
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
    B+ (Cautious / Stricter Risk) setups, integrating Level-2 DOM Depth of Market
    and Derivatives Funding / Liquidation Heatmaps.
    """

    @staticmethod
    def grade_setup(
        direction: str,
        current_price: float,
        setup_score: int,
        confirmations: Optional[ConfirmationsResult],
        mtf_context: Optional[MultiTimeframeContext],
        dealing_range: Optional[DealingRange],
        displacement: Optional[DisplacementResult],
        orderbook: Optional[OrderBookAnalysis] = None,
        derivatives: Optional[DerivativesIntel] = None
    ) -> SetupGradeResult:
        dir_upper = direction.upper()

        # 1. Unified Macro Consensus Check (Bans opposing counter-trend setups)
        macro_aligned = False
        if mtf_context:
            macro_4h = (mtf_context.macro_bias_4h or "").upper()
            trend_1h = (mtf_context.trend_1h or "").upper()

            # Hard Macro Consensus Lock: 4H & 1H Trend Governs All 10 Models (Zero Counter-Trend)
            if (macro_4h == "BEARISH" or trend_1h == "BEARISH") and dir_upper == "LONG":
                return SetupGradeResult(
                    grade="REJECTED",
                    is_tradeable=False,
                    summary="Rejected by Trend Lock: 1H/4H Trend is BEARISH (All Longs Banned)."
                )
            if (macro_4h == "BULLISH" or trend_1h == "BULLISH") and dir_upper == "SHORT":
                return SetupGradeResult(
                    grade="REJECTED",
                    is_tradeable=False,
                    summary="Rejected by Trend Lock: 1H/4H Trend is BULLISH (All Shorts Banned)."
                )

            if dir_upper == "LONG":
                macro_aligned = (macro_4h == "BULLISH" and trend_1h != "BEARISH")
            elif dir_upper == "SHORT":
                macro_aligned = (macro_4h == "BEARISH" and trend_1h != "BULLISH")
        else:
            macro_aligned = True


        # 2. Check Premium vs Discount Zone
        pd_zone_ok, pd_desc = EquilibriumEngine.validate_setup_zone(dir_upper, current_price, dealing_range)

        # 3. Displacement
        displacement_ok = displacement.detected if displacement else False

        # 4. Confirmations count
        conf_count = confirmations.passed_count if confirmations else 0

        # 5. Level-2 DOM & Derivatives Confluence
        dom_ok = False
        liq_ok = False
        effective_score = setup_score

        if orderbook:
            if dir_upper == "LONG" and (orderbook.imbalance_bias == "BULLISH_IMBALANCE" or orderbook.imbalance_ratio_top20 >= 1.25):
                dom_ok = True
                effective_score = min(effective_score + 5, 100)
            elif dir_upper == "SHORT" and (orderbook.imbalance_bias == "BEARISH_IMBALANCE" or orderbook.imbalance_ratio_top20 <= 0.80):
                dom_ok = True
                effective_score = min(effective_score + 5, 100)

        if derivatives:
            if dir_upper == "LONG" and (derivatives.squeeze_potential == "SHORT_SQUEEZE_PRIME" or derivatives.funding_rate <= 0.005):
                liq_ok = True
                effective_score = min(effective_score + 5, 100)
            elif dir_upper == "SHORT" and (derivatives.squeeze_potential == "LONG_SQUEEZE_PRIME" or derivatives.funding_rate >= 0.015):
                liq_ok = True
                effective_score = min(effective_score + 5, 100)

        # Hard Reject: Counter-trend on wrong side of dealing range with low score
        if not macro_aligned and not pd_zone_ok:
            return SetupGradeResult(
                grade="REJECTED",
                is_tradeable=False,
                summary="Rejected: Counter-macro trend in opposing Premium/Discount zone."
            )

        # Evaluate A+ Setup
        if (effective_score >= 85 and conf_count >= 5 and macro_aligned and pd_zone_ok):
            return SetupGradeResult(
                grade="A+",
                is_tradeable=True,
                macro_aligned=True,
                pd_zone_ok=True,
                displacement_ok=displacement_ok,
                dom_confluence=dom_ok,
                liquidation_confluence=liq_ok,
                confirmations_count=conf_count,
                score=effective_score,
                sl_atr_multiplier=0.35,
                target_1_rr=1.8,
                target_2_rr=2.5,
                breakeven_trigger_r=0.8,
                badge="🌟 GRADE: A+ (INSTITUTIONAL CONVICTION)",
                summary=f"A+ Institutional Setup: Score {effective_score}, {conf_count}/7 Confirms, Macro Aligned, {pd_desc}"
            )

        # Evaluate B+ Setup (Meets trading threshold but requires stricter risk)
        if (effective_score >= 70 and conf_count >= 4):
            return SetupGradeResult(
                grade="B+",
                is_tradeable=True,
                macro_aligned=macro_aligned,
                pd_zone_ok=pd_zone_ok,
                displacement_ok=displacement_ok,
                dom_confluence=dom_ok,
                liquidation_confluence=liq_ok,
                confirmations_count=conf_count,
                score=effective_score,
                sl_atr_multiplier=0.15,       # Stricter tight SL
                target_1_rr=1.6,              # Quick TP (Min 1.6R)
                target_2_rr=1.8,              # Cautious T2
                breakeven_trigger_r=0.6,      # Rapid Breakeven protection
                badge="⚡ GRADE: B+ (STRICT RISK / TIGHT SL)",
                summary=f"B+ Setup: Score {effective_score}, {conf_count}/7 Confirms. Stricter SL (0.15 ATR) & Quick TP (1.6R) active."
            )

        return SetupGradeResult(
            grade="REJECTED",
            is_tradeable=False,
            confirmations_count=conf_count,
            score=effective_score,
            badge="REJECTED",
            summary=f"Rejected: Score {effective_score}/100 and Confirms {conf_count}/7 did not meet B+ qualification bar."
        )

