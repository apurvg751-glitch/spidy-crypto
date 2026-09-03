from typing import Optional
from pydantic import BaseModel


class SetupScoreBreakdown(BaseModel):
    # Standard Fields (backward compatible with all models)
    trend_score: int = 0          # Max 25
    sweep_score: int = 0          # Max 25
    bos_score: int = 0            # Max 20
    volume_score: int = 0         # Max 15
    rr_score: int = 0             # Max 15

    # 7-Pillar Institutional Confluence Breakdown (Model 10)
    htf_macro_score: int = 0      # Max 20 (4H / 1H Alignment)
    liquidity_sweep_score: int = 0# Max 20 (BSL/SSL/EQ Extremes Purge)
    displacement_mss_score: int = 0# Max 15 (MSS with Body >= 55%)
    pd_array_score: int = 0       # Max 15 (Discount for Long, Premium for Short)
    ob_fvg_score: int = 0         # Max 15 (Order Block + FVG Confluence)

    total_score: int = 0          # 0 - 100


def calculate_setup_score(
    trend_aligned: bool,
    trend_neutral: bool,
    sweep_confirmed: bool,
    bos_confirmed: bool,
    volume_confirmed: bool,
    rvol: float,
    risk_reward: float
) -> SetupScoreBreakdown:
    """
    Standard deterministic setup quality score (0 to 100).
    """
    trend_score = 25 if trend_aligned else (12 if trend_neutral else 0)
    sweep_score = 25 if sweep_confirmed else 0
    bos_score = 20 if bos_confirmed else 0

    if rvol >= 1.5:
        volume_score = 15
    elif rvol >= 1.2 or volume_confirmed:
        volume_score = 12
    elif rvol >= 1.0:
        volume_score = 6
    else:
        volume_score = 0

    if risk_reward >= 2.5:
        rr_score = 15
    elif risk_reward >= 2.0:
        rr_score = 12
    elif risk_reward >= 1.5:
        rr_score = 8
    else:
        rr_score = 0

    total = trend_score + sweep_score + bos_score + volume_score + rr_score

    return SetupScoreBreakdown(
        trend_score=trend_score,
        sweep_score=sweep_score,
        bos_score=bos_score,
        volume_score=volume_score,
        rr_score=rr_score,
        total_score=min(max(total, 0), 100)
    )


def calculate_institutional_100_score(
    htf_aligned: bool,
    sweep_confirmed: bool,
    displacement_mss: bool,
    pd_array_confirmed: bool,
    ob_fvg_confluence: bool,
    volume_confirmed: bool,
    rvol: float,
    risk_reward: float
) -> SetupScoreBreakdown:
    """
    Computes the 7-Pillar Institutional Confluence Score for 100/100 Sniper setups:
    1. HTF Macro Bias (4H/1H): 20 pts
    2. Liquidity Sweep (BSL/SSL or EQH/EQL): 20 pts
    3. Market Structure Shift (MSS) + Displacement: 15 pts
    4. PD Array (Discount for Long / Premium for Short): 15 pts
    5. Order Block + FVG Confluence: 15 pts
    6. Institutional Volume Expansion (RVOL >= 1.25): 10 pts
    7. Asymmetric Risk-Reward (>= 2.5R): 5 pts
    Total = 100/100!
    """
    # 1. HTF Macro (20 pts)
    htf_score = 20 if htf_aligned else 0

    # 2. Liquidity Sweep (20 pts)
    sweep_score = 20 if sweep_confirmed else 0

    # 3. MSS + Displacement (15 pts)
    mss_score = 15 if displacement_mss else 0

    # 4. PD Array Equilibrium (15 pts)
    pd_score = 15 if pd_array_confirmed else 0

    # 5. OB + FVG (15 pts)
    ob_fvg_score = 15 if ob_fvg_confluence else 0

    # 6. Volume (10 pts)
    vol_score = 10 if (rvol >= 1.25 or volume_confirmed) else (5 if rvol >= 1.0 else 0)

    # 7. RR (5 pts)
    rr_score = 5 if risk_reward >= 2.4 else (3 if risk_reward >= 1.8 else 0)

    total = htf_score + sweep_score + mss_score + pd_score + ob_fvg_score + vol_score + rr_score

    return SetupScoreBreakdown(
        htf_macro_score=htf_score,
        liquidity_sweep_score=sweep_score,
        displacement_mss_score=mss_score,
        pd_array_score=pd_score,
        ob_fvg_score=ob_fvg_score,
        volume_score=vol_score,
        rr_score=rr_score,
        trend_score=htf_score,
        sweep_score=sweep_score,
        bos_score=mss_score,
        total_score=min(max(total, 0), 100)
    )
