import pytest
from datetime import datetime, timezone
from market_data.models import Candle
from structure.kill_zones import KillZoneEngine
from structure.target_snapper import TargetSnapper
from structure.equilibrium import DealingRange
from indicators.smt_divergence import SMTDivergenceEngine
from telegram.briefings import SessionBriefingGenerator


def make_candle(t: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol="BTCUSD", time=t, open=o, high=h, low=l, close=c, volume=100.0)


def test_kill_zone_engine_session_detection():
    # 08:30 UTC = 14:00 IST -> London Open Kill Zone
    dt_london = datetime(2026, 9, 3, 8, 30, tzinfo=timezone.utc)
    status_london = KillZoneEngine.evaluate(current_utc_time=dt_london)
    assert status_london.session_name == "LONDON_OPEN"
    assert status_london.is_active_kill_zone is True
    assert status_london.confidence_multiplier == 1.25

    # 14:30 UTC = 20:00 IST -> New York Open Kill Zone
    dt_ny = datetime(2026, 9, 3, 14, 30, tzinfo=timezone.utc)
    status_ny = KillZoneEngine.evaluate(current_utc_time=dt_ny)
    assert status_ny.session_name == "NEW_YORK_OPEN"
    assert status_ny.is_active_kill_zone is True
    assert status_ny.confidence_multiplier == 1.30

    # 22:00 UTC = 03:30 IST -> Off Hours
    dt_off = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
    status_off = KillZoneEngine.evaluate(current_utc_time=dt_off)
    assert status_off.session_name == "OFF_HOURS"
    assert status_off.is_active_kill_zone is False


def test_target_snapper_anchors_to_real_swings():
    # Candles with a physical swing high at 78500
    candles = [
        make_candle(100 * i, 77000 + i * 20, 77050 + i * 20, 76950 + i * 20, 77000 + i * 20)
        for i in range(20)
    ]
    candles[10] = make_candle(1000, 78200, 78500, 78100, 78400)  # Physical Swing High 78500

    dr = DealingRange(
        range_high=79000.0, range_low=76000.0, range_span=3000.0,
        equilibrium=77500.0, premium_zone=77500.0, discount_zone=77500.0,
        deep_premium=78250.0, deep_discount=76750.0, current_position_pct=0.4,
        zone="DISCOUNT", is_valid=True, description="Test Range"
    )

    snapped = TargetSnapper.snap_targets(
        direction="LONG",
        entry=77200.0,
        stop_loss=76800.0,  # Risk = 400
        candles_15m=candles,
        dealing_range=dr
    )

    assert snapped.target_1 == 78500.0  # Snapped to physical swing high!
    assert snapped.rr_1 >= 1.6
    assert "PHYSICAL_SWING_HIGH" in snapped.target_1_type


def test_smt_divergence_detection():
    # Window 1: BTC high 77000, ETH high 2450
    # Window 2: BTC high 77500 (Higher High), ETH high 2420 (Lower High) -> Bearish SMT!
    btc_candles = [
        make_candle(100, 76800, 77000, 76700, 76900),
        make_candle(200, 76900, 76950, 76800, 76850),
        make_candle(300, 76850, 77500, 76800, 77400),  # HH
        make_candle(400, 77400, 77450, 77200, 77300),
    ]

    eth_candles = [
        make_candle(100, 2400, 2450, 2390, 2440),      # High 2450
        make_candle(200, 2440, 2430, 2410, 2420),
        make_candle(300, 2420, 2420, 2390, 2410),      # LH 2420 (Failed to make HH!)
        make_candle(400, 2410, 2415, 2395, 2400),
    ]

    res = SMTDivergenceEngine.evaluate(btc_candles, eth_candles, lookback=4)
    assert res.detected is True
    assert res.divergence_type == "BEARISH_SMT"
    assert "Institutional Distribution" in res.description


def test_session_briefing_formatter():
    kz = KillZoneEngine.evaluate()
    prices = {"BTCUSD": 78000.0, "ETHUSD": 2410.0, "SOLUSD": 101.0}
    morning_msg = SessionBriefingGenerator.format_morning_briefing(prices, kz)
    assert "MORNING MACRO BRIEFING" in morning_msg
    assert "BTCUSD" in morning_msg
    assert "ASIAN LIQUIDITY POOLS" in morning_msg

    ny_msg = SessionBriefingGenerator.format_ny_briefing(prices, kz)
    assert "NEW YORK OPEN BRIEFING" in ny_msg
    assert "NEW YORK AM KILL ZONE" in ny_msg
