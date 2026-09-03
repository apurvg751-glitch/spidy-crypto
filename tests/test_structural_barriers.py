import pytest
from market_data.models import Candle
from structure.barrier_engine import BarrierEngine, BarrierValidationResult
from structure.equilibrium import DealingRange


def make_test_candle(time_sec: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        symbol="BTCUSD",
        time=time_sec,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0
    )


def test_barrier_engine_finds_ceilings_and_floors():
    candles = [
        make_test_candle(100, 77000, 77500, 76900, 77400),
        make_test_candle(200, 77400, 77800, 77300, 77750),  # Swing High 77800 (Ceiling)
        make_test_candle(300, 77750, 77760, 77100, 77200),
        make_test_candle(400, 77200, 77300, 76800, 76900),  # Swing Low 76800 (Floor)
        make_test_candle(500, 76900, 77400, 76850, 77300),
        make_test_candle(600, 77300, 77820, 77250, 77800),  # Double Top / Ceiling 77820
        make_test_candle(700, 77800, 77810, 77400, 77450),
        make_test_candle(800, 77450, 77500, 77100, 77150),
        make_test_candle(900, 77150, 77300, 77000, 77250),
        make_test_candle(1000, 77250, 77400, 77100, 77350),
        make_test_candle(1100, 77350, 77500, 77200, 77450),
        make_test_candle(1200, 77450, 77600, 77300, 77550),
        make_test_candle(1300, 77550, 77700, 77400, 77650),
        make_test_candle(1400, 77650, 77750, 77500, 77700),
        make_test_candle(1500, 77700, 77780, 77600, 77730),
        make_test_candle(1600, 77730, 77750, 77650, 77700)
    ]

    ceilings, floors = BarrierEngine.find_major_barriers(candles)
    assert len(ceilings) >= 1
    assert max(ceilings) >= 77800.0


def test_long_blocked_directly_under_resistance_ceiling():
    """Validates that buying at 77730 with major ceiling at 77800 is REJECTED (Room to Run filter)."""
    candles = [
        make_test_candle(i * 100, 77000 + (i * 20), 77050 + (i * 20), 76950 + (i * 20), 77020 + (i * 20))
        for i in range(16)
    ]
    # Inject a major ceiling at 77800
    candles[5] = make_test_candle(500, 77400, 77800, 77300, 77750)
    candles[6] = make_test_candle(600, 77750, 77760, 77100, 77200)

    # Current price is 77731 (only 69 pts / 0.08% below 77800 ceiling)
    res = BarrierEngine.validate_room_to_run(
        direction="LONG",
        current_price=77731.0,
        candles_15m=candles,
        atr=250.0
    )
    assert res.is_valid is False
    assert "LONG Blocked" in res.reason
    assert "No Room to Run" in res.reason


def test_short_blocked_directly_above_support_floor():
    """Validates that selling right into support floor is REJECTED."""
    candles = [
        make_test_candle(i * 100, 77500 - (i * 20), 77550 - (i * 20), 77450 - (i * 20), 77480 - (i * 20))
        for i in range(16)
    ]
    # Inject a major support floor at 76800
    candles[5] = make_test_candle(500, 77200, 77300, 76800, 76900)
    candles[6] = make_test_candle(600, 76900, 77400, 76850, 77300)

    # Current price is 76850 (only 50 pts / 0.06% above 76800 floor)
    res = BarrierEngine.validate_room_to_run(
        direction="SHORT",
        current_price=76850.0,
        candles_15m=candles,
        atr=250.0
    )
    assert res.is_valid is False
    assert "SHORT Blocked" in res.reason


def test_whole_structure_roof_and_floor_zone_hard_bans():
    """Validates Top 25% bans LONGs and Bottom 25% bans SHORTs."""
    dr = DealingRange(
        range_high=78000.0,
        range_low=76000.0,
        range_span=2000.0,
        equilibrium=77000.0,
        premium_zone=77000.0,
        discount_zone=77000.0,
        deep_premium=77500.0,
        deep_discount=76500.0,
        current_position_pct=0.85,
        zone="DEEP_PREMIUM",
        is_valid=True,
        description="Dealing Range [76000 - 78000]"
    )

    candles = [make_test_candle(i * 100, 77000, 77100, 76900, 77050) for i in range(15)]

    # Price at 77700 (85% of range = Roof Zone)
    res_long = BarrierEngine.validate_room_to_run("LONG", 77700.0, candles, atr=150.0, dealing_range=dr)
    assert res_long.is_valid is False
    assert "ROOF ZONE" in res_long.reason

    # Price at 76300 (15% of range = Floor Zone)
    res_short = BarrierEngine.validate_room_to_run("SHORT", 76300.0, candles, atr=150.0, dealing_range=dr)
    assert res_short.is_valid is False
    assert "FLOOR ZONE" in res_short.reason
