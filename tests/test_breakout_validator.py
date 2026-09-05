import pytest
from market_data.models import Candle
from structure.breakout_validator import BreakoutValidator


def test_real_bullish_breakout():
    """Real bullish breakout has strong body >=60%, closes above level, RVOL >= 1.25."""
    candles = [Candle(time=i*300, open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, is_closed=True) for i in range(25)]
    # Breakout candle: strong green body, closes well above 102.0 with high volume
    candles.append(Candle(time=25*300, open=101.5, high=104.0, low=101.3, close=103.8, volume=500.0, is_closed=True))

    res = BreakoutValidator.validate_breakout(
        candles=candles,
        breakout_level=102.0,
        direction="LONG",
        atr=1.5
    )

    assert res.is_real_breakout is True
    assert res.is_fake_breakout is False
    assert res.recommended_action == "ENTER_BREAKOUT"


def test_fake_bullish_breakout_bull_trap():
    """Fake bullish breakout has long upper wick, closes below or weak body."""
    candles = [Candle(time=i*300, open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, is_closed=True) for i in range(25)]
    # Bull trap candle: spikes to 105.0 above 102.0, but closes back down at 101.0 with long upper wick
    candles.append(Candle(time=25*300, open=100.8, high=105.0, low=100.5, close=101.0, volume=300.0, is_closed=True))

    res = BreakoutValidator.validate_breakout(
        candles=candles,
        breakout_level=102.0,
        direction="LONG",
        atr=1.5
    )

    assert res.is_real_breakout is False
    assert res.is_fake_breakout is True
    assert res.trap_type == "BULL_TRAP"
    assert res.recommended_action == "REVERSE_TRAP"


def test_real_bearish_breakout():
    """Real bearish breakout has strong red body >=60%, closes below level, RVOL >= 1.25."""
    candles = [Candle(time=i*300, open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, is_closed=True) for i in range(25)]
    # Breakdown candle: strong red body, closes below 98.0 with high volume
    candles.append(Candle(time=25*300, open=98.5, high=98.6, low=96.0, close=96.2, volume=500.0, is_closed=True))

    res = BreakoutValidator.validate_breakout(
        candles=candles,
        breakout_level=98.0,
        direction="SHORT",
        atr=1.5
    )

    assert res.is_real_breakout is True
    assert res.is_fake_breakout is False
    assert res.recommended_action == "ENTER_BREAKOUT"


def test_fake_bearish_breakout_bear_trap():
    """Fake bearish breakdown wicks below level but closes back above."""
    candles = [Candle(time=i*300, open=100.0, high=101.0, low=99.5, close=100.5, volume=100.0, is_closed=True) for i in range(25)]
    # Bear trap candle: wicks down to 95.0 below 98.0, but closes back up at 99.0
    candles.append(Candle(time=25*300, open=98.2, high=99.5, low=95.0, close=99.0, volume=300.0, is_closed=True))

    res = BreakoutValidator.validate_breakout(
        candles=candles,
        breakout_level=98.0,
        direction="SHORT",
        atr=1.5
    )

    assert res.is_real_breakout is False
    assert res.is_fake_breakout is True
    assert res.trap_type == "BEAR_TRAP"
    assert res.recommended_action == "REVERSE_TRAP"
