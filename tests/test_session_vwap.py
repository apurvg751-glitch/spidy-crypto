import pytest
import time
from market_data.models import Candle
from structure.session_vwap import SessionVWAPEngine


def test_session_vwap_calculation():
    now = int(time.time())
    candles = []
    # Create 20 candles with prices from 2400 to 2420
    for i in range(20):
        t = now - ((20 - i) * 300)
        p = 2400.0 + i
        candles.append(Candle(
            time=t,
            open=p,
            high=p + 2.0,
            low=p - 2.0,
            close=p + 1.0,
            volume=100.0 * (i + 1),
            is_closed=True
        ))

    res = SessionVWAPEngine.calculate(candles, current_price=2415.0)
    assert res is not None
    assert res.vwap > 2400.0
    assert res.vah > res.vwap
    assert res.val < res.vwap
    assert res.poc > 0.0
    assert "Session" in res.session_name


def test_session_vwap_above_vah_reversal():
    now = int(time.time())
    candles = [
        Candle(time=now - (i * 300), open=100.0, high=101.0, low=99.0, close=100.0, volume=50.0, is_closed=True)
        for i in range(15)
    ]
    # Price is way above VAH
    res = SessionVWAPEngine.calculate(candles, current_price=105.0)
    assert res is not None
    assert res.current_relation == "ABOVE_VAH"
    assert res.bias_confluence == "BEARISH_PREMIUM"
    assert res.confluence_score == 10
