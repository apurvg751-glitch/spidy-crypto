import pytest
from market_data.models import Candle, MultiTimeframeContext, ConfirmationsResult
from structure.equilibrium import EquilibriumEngine, DealingRange
from indicators.displacement import DisplacementEngine
from strategy.setup_grading import SetupGradingEngine
from risk_engine.risk_calculator import RiskEngine


def generate_candles():
    base = 2400.0
    candles = []
    # Create 30 candles from 2350 to 2450 (Span: 100, Eq: 2400)
    for i in range(30):
        p = 2350.0 + (i * 3.3)
        candles.append(Candle(
            symbol="ETHUSD",
            time=1700000000 + (i * 300),
            open=p,
            high=p + 2.0,
            low=p - 2.0,
            close=p + 1.0,
            volume=100.0
        ))
    return candles


def test_equilibrium_engine():
    candles = generate_candles()
    dr = EquilibriumEngine.calculate_range(candles)
    assert dr is not None
    assert dr.range_low < dr.equilibrium < dr.range_high
    assert dr.equilibrium == pytest.approx(2400.0, abs=5.0)

    # Test LONG in Deep Discount (price near low)
    valid_long, desc_long = EquilibriumEngine.validate_setup_zone("LONG", 2360.0, dr)
    assert valid_long is True
    assert "DISCOUNT" in desc_long

    # Test LONG in Premium (price near high) -> must be rejected
    invalid_long, desc_inv = EquilibriumEngine.validate_setup_zone("LONG", 2445.0, dr)
    assert invalid_long is False
    assert "Rejected" in desc_inv

    # Test SHORT in Premium -> must be validated
    valid_short, desc_short = EquilibriumEngine.validate_setup_zone("SHORT", 2445.0, dr)
    assert valid_short is True
    assert "PREMIUM" in desc_short


def test_displacement_engine():
    # 1. Normal candles
    candles = generate_candles()
    res1 = DisplacementEngine.evaluate(candles)
    # 2. Add an aggressive displacement expansion candle
    last_p = candles[-1].close
    candles.append(Candle(
        symbol="ETHUSD",
        time=candles[-1].time + 300,
        open=last_p,
        high=last_p + 25.0,
        low=last_p - 1.0,
        close=last_p + 24.0,  # 96% body, 6x range expansion
        volume=500.0
    ))
    res2 = DisplacementEngine.evaluate(candles)
    assert res2.detected is True
    assert res2.direction == "BULLISH"
    assert res2.body_ratio >= 0.55
    assert res2.expansion_ratio >= 1.15


def test_setup_grading_a_plus_and_b_plus():
    candles = generate_candles()
    dr = EquilibriumEngine.calculate_range(candles)
    disp = DisplacementEngine.evaluate(candles)

    # Context: Bullish Macro
    mtf_bullish = MultiTimeframeContext(
        symbol="ETHUSD",
        macro_bias_4h="Bullish",
        trend_1h="Bullish",
        exec_context_15m="Bullish",
        struct_5m="Bullish",
        confluence_score=90
    )

    confs_7 = ConfirmationsResult(
        passed_count=6,
        is_qualified=True,
        rating="STRONG CONVICTION"
    )

    # 1. Test A+ Setup: Long in Discount, Bullish Macro, Score 88, 6/7 Confirms
    res_a = SetupGradingEngine.grade_setup(
        direction="LONG",
        current_price=2365.0,
        setup_score=88,
        confirmations=confs_7,
        mtf_context=mtf_bullish,
        dealing_range=dr,
        displacement=disp
    )
    assert res_a.grade == "A+"
    assert res_a.is_tradeable is True
    assert res_a.target_2_rr == 2.5
    assert res_a.sl_atr_multiplier == 0.35

    # 2. Test B+ Setup: Score 75, 4 Confirms -> Gets Stricter SL (0.15) and Quick TP (1.4R)
    confs_4 = ConfirmationsResult(
        passed_count=4,
        is_qualified=True,
        rating="QUALIFIED"
    )
    res_b = SetupGradingEngine.grade_setup(
        direction="LONG",
        current_price=2370.0,
        setup_score=76,
        confirmations=confs_4,
        mtf_context=mtf_bullish,
        dealing_range=dr,
        displacement=disp
    )
    assert res_b.grade == "B+"
    assert res_b.is_tradeable is True
    assert res_b.sl_atr_multiplier == 0.15  # Stricter SL
    assert res_b.target_1_rr == 1.6         # Stricter quick TP (Min 1.6R)
    assert res_b.breakeven_trigger_r == 0.6 # Faster Breakeven


def test_stricter_risk_levels_on_b_plus():
    levels_a = RiskEngine.calculate_levels("LONG", 2400.0, 2390.0, atr=10.0, grade="A+")
    levels_b = RiskEngine.calculate_levels("LONG", 2400.0, 2390.0, atr=10.0, grade="B+")

    # B+ setup stop loss should be tighter (higher stop level for LONG)
    assert levels_b.stop_loss > levels_a.stop_loss
    # B+ setup Target 1 should be closer/quicker (1.6R vs 1.8R)
    assert levels_b.target_1 < levels_a.target_1
