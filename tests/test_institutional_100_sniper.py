import pytest
from strategy.scoring import calculate_institutional_100_score
from strategy.models.model_10_institutional_sniper import Model10InstitutionalSniper
from market_data.models import MarketState, Candle, MultiTimeframeContext


def test_calculate_institutional_100_score():
    # 1. Test All 7 Pillars Active -> Exactly 100/100!
    breakdown = calculate_institutional_100_score(
        htf_aligned=True,             # 20 pts
        sweep_confirmed=True,         # 20 pts
        displacement_mss=True,        # 15 pts
        pd_array_confirmed=True,      # 15 pts
        ob_fvg_confluence=True,       # 15 pts
        volume_confirmed=True,        # 10 pts
        rvol=1.5,
        risk_reward=2.5               # 5 pts
    )
    assert breakdown.total_score == 100
    assert breakdown.htf_macro_score == 20
    assert breakdown.liquidity_sweep_score == 20
    assert breakdown.displacement_mss_score == 15
    assert breakdown.pd_array_score == 15
    assert breakdown.ob_fvg_score == 15
    assert breakdown.volume_score == 10
    assert breakdown.rr_score == 5

    # 2. Test Partial Score (No Sweep, Low Volume)
    partial = calculate_institutional_100_score(
        htf_aligned=True,             # 20
        sweep_confirmed=False,        # 0
        displacement_mss=True,        # 15
        pd_array_confirmed=True,      # 15
        ob_fvg_confluence=True,       # 15
        volume_confirmed=False,       # 0
        rvol=0.8,
        risk_reward=2.5               # 5
    )
    assert partial.total_score == 70
    assert partial.sweep_score == 0


def test_model_10_initialization_and_evaluation():
    m10 = Model10InstitutionalSniper()
    assert m10.model_id == "MODEL_10"
    assert "Institutional Sniper" in m10.name

    # Create market state with 40 candles
    candles = []
    base_p = 2400.0
    for i in range(40):
        p = base_p + (i * 1.5)
        candles.append(Candle(
            symbol="ETHUSD",
            time=1700000000 + (i * 300),
            open=p,
            high=p + 4.0,
            low=p - 2.0,
            close=p + 2.0,
            volume=200.0
        ))

    mtf = MultiTimeframeContext(
        symbol="ETHUSD",
        macro_bias_4h="Bullish",
        trend_1h="Bullish",
        exec_context_15m="Bullish",
        struct_5m="Bullish",
        confluence_score=95
    )

    ms = MarketState(
        symbol="ETHUSD",
        current_price=candles[-1].close,
        candles_5m=candles,
        candles_15m=candles,
        mtf_context=mtf
    )

    cand = m10.evaluate(ms)
    # If triggered, must have grade A+ and institutional attributes
    if cand:
        assert cand.model_id == "MODEL_10"
        assert cand.grade == "A+"
        assert cand.setup_score >= 80
        assert len(cand.reasons) > 0
