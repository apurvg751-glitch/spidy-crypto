import pytest
from structure.trailing_engine import TrailingStopEngine


def test_trailing_stop_breakeven_milestone():
    # Long trade: Entry 2400, Risk 20 (Stop 2380)
    # Price reaches 2418 (+0.9R) -> should move to Breakeven (2400)
    res = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=2400.0,
        original_stop=2380.0,
        current_stop=2380.0,
        current_price=2418.0,
        peak_favorable_price=2418.0,
        atr=10.0
    )
    assert res.stop_moved is True
    assert res.new_stop >= 2400.0


def test_trailing_stop_milestone_ratchets():
    # Long trade: Entry 2400, Risk 20 (Stop 2380)
    # Price reaches 2445 (+2.25R) -> should lock +1.0R (2420.0)
    res = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=2400.0,
        original_stop=2380.0,
        current_stop=2400.0,
        current_price=2440.0,
        peak_favorable_price=2445.0,
        atr=8.0
    )
    assert res.stop_moved is True
    assert res.new_stop >= 2420.0
    assert res.locked_r >= 1.0


def test_trailing_stop_never_loosens():
    # If price pulls back, stop must NOT loosen
    res = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=2400.0,
        original_stop=2380.0,
        current_stop=2420.0,
        current_price=2425.0,
        peak_favorable_price=2445.0,
        atr=8.0
    )
    assert res.new_stop >= 2420.0


def test_trailing_stop_short_ratchets():
    # Short trade: Entry 100.0, Risk 2.0 (Stop 102.0)
    # Price drops to 96.0 (+2.0R) -> should lock +1.0R (Stop 98.0)
    res = TrailingStopEngine.evaluate_trail(
        direction="SHORT",
        entry=100.0,
        original_stop=102.0,
        current_stop=102.0,
        current_price=96.5,
        peak_favorable_price=96.0,
        atr=1.0
    )
    assert res.stop_moved is True
    assert res.new_stop <= 98.0


def test_structural_trailing_higher_low_long():
    from tests.conftest import make_candle
    # LONG trade: Entry 100.0, Stop 95.0 (Risk = 5.0).
    # Current price 108.0 (+1.6R).
    # 5M candles form a confirmed Higher Low at 104.0 (index 4).
    # Trailing stop should ratchet to protect above 100 and near 104.0!
    candles = [
        make_candle(1, 100, 102, 99, 101),
        make_candle(2, 101, 105, 100, 104),
        make_candle(3, 104, 106, 104.5, 105), # Low 104.5
        make_candle(4, 105, 105.5, 104.2, 104.5), # Low 104.2
        make_candle(5, 104.5, 105.0, 104.0, 104.8), # Low 104.0 (Swing Low)
        make_candle(6, 104.8, 107.0, 104.5, 106.5), # Low 104.5
        make_candle(7, 106.5, 108.5, 106.0, 108.0), # Low 106.0
    ]

    res = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=100.0,
        original_stop=95.0,
        current_stop=100.25,
        current_price=108.0,
        peak_favorable_price=108.5,
        atr=1.5,
        candles_5m=candles,
        symbol="SOLUSD"
    )
    assert res.stop_moved is True
    assert res.new_stop > 100.25
    assert "Higher Low" in res.trail_reason


def test_structural_trailing_lower_high_short():
    from tests.conftest import make_candle
    # SHORT trade: Entry 100.0, Stop 105.0 (Risk = 5.0).
    # Current price 92.0 (+1.6R).
    # 5M candles form a confirmed Lower High at 96.0 (index 4).
    # Trailing stop should ratchet to protect below 100 and near 96.0!
    candles = [
        make_candle(1, 100, 101, 98, 99),
        make_candle(2, 99, 100, 95, 96),
        make_candle(3, 96, 95.5, 94, 94.5), # High 95.5
        make_candle(4, 94.5, 95.8, 94.2, 95.5), # High 95.8
        make_candle(5, 95.5, 96.0, 95.0, 95.2), # High 96.0 (Swing High)
        make_candle(6, 95.2, 95.5, 93.0, 93.5), # High 95.5
        make_candle(7, 93.5, 94.0, 91.5, 92.0), # High 94.0
    ]

    res = TrailingStopEngine.evaluate_trail(
        direction="SHORT",
        entry=100.0,
        original_stop=105.0,
        current_stop=99.75,
        current_price=92.0,
        peak_favorable_price=91.5,
        atr=1.5,
        candles_5m=candles,
        symbol="SOLUSD"
    )
    assert res.stop_moved is True
    assert res.new_stop < 99.75
    assert "Lower High" in res.trail_reason

