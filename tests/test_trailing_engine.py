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
