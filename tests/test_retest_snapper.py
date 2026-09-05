import pytest
from market_data.models import FairValueGap
from structure.order_blocks import OrderBlock
from strategy.retest_snapper import RetestSnapper


def test_retest_snapper_long_fvg():
    # Long setup with Bullish FVG below current close
    fvg = FairValueGap(
        id="fvg_1",
        symbol="BTCUSD",
        direction="BULLISH",
        top=65000.0,
        bottom=64800.0,
        candle_index=10,
        creation_time=1700000000
    )
    res = RetestSnapper.calculate_optimal_entry(
        symbol="BTCUSD",
        direction="LONG",
        current_close=65200.0,
        atr=200.0,
        active_fvg=fvg
    )
    # Midpoint of 65000 and 64800 is 64900
    assert res.entry_type == "FVG_MIDPOINT"
    assert res.optimal_entry == 64900.0
    assert res.discount_pips == 300.0


def test_retest_snapper_short_ob():
    # Short setup with Bearish OB above current close
    ob = OrderBlock(
        id="ob_1",
        symbol="ETHUSD",
        direction="BEARISH",
        top=3550.0,
        bottom=3530.0,
        candle_index=5,
        creation_time=1700000000
    )
    res = RetestSnapper.calculate_optimal_entry(
        symbol="ETHUSD",
        direction="SHORT",
        current_close=3500.0,
        atr=20.0,
        active_ob=ob
    )
    # Midpoint of 3550 and 3530 is 3540
    assert res.entry_type == "OB_MIDPOINT"
    assert res.optimal_entry == 3540.0
    assert res.discount_pips == 40.0


def test_retest_snapper_fallback_discount():
    # When no FVG or OB available, fallback to 0.15x ATR
    res = RetestSnapper.calculate_optimal_entry(
        symbol="SOLUSD",
        direction="LONG",
        current_close=150.0,
        atr=2.0
    )
    assert res.entry_type == "PULLBACK_DISCOUNT"
    # 150.0 - 0.15 * 2.0 = 149.70
    assert res.optimal_entry == 149.70
