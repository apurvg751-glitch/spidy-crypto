import pytest
import time
from market_data.models import Candle
from strategy.btc_anchor import BtcAnchorEngine


def _make_candle(timestamp: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        time=timestamp,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
        total_range=h - l,
        body_size=abs(c - o),
        upper_wick=h - max(o, c),
        lower_wick=min(o, c) - l,
        is_bullish=c >= o
    )


def test_btc_anchor_permits_btc_itself():
    # BTCUSD should never block BTCUSD
    res = BtcAnchorEngine.evaluate_btc_alignment("BTCUSD", "LONG", [])
    assert res.is_allowed is True
    assert res.btc_trend == "SELF"


def test_btc_anchor_blocks_altcoin_long_when_btc_bearish():
    # 35 candles in clear downtrend (Price < EMA20 <= EMA50)
    candles = []
    base_price = 70000.0
    base_time = 1700000000
    for i in range(35):
        price = base_price - (i * 100.0)
        candles.append(_make_candle(base_time + (i * 900), price + 20, price + 30, price - 20, price))

    res = BtcAnchorEngine.evaluate_btc_alignment("ETHUSD", "LONG", candles)
    assert res.is_allowed is False
    assert res.btc_trend == "BEARISH"
    assert "BLOCKED BY BTC MACRO ANCHOR" in res.rejection_reason


def test_btc_anchor_permits_altcoin_long_when_btc_bullish():
    # 35 candles in clear uptrend (Price > EMA20 >= EMA50)
    candles = []
    base_price = 60000.0
    base_time = 1700000000
    for i in range(35):
        price = base_price + (i * 150.0)
        candles.append(_make_candle(base_time + (i * 900), price - 20, price + 30, price - 30, price))

    res = BtcAnchorEngine.evaluate_btc_alignment("SOLUSD", "LONG", candles)
    assert res.is_allowed is True
    assert res.btc_trend == "BULLISH"


def test_high_conviction_setup_overrides_mild_btc_bias():
    # BTC slightly bullish (last close 79471 > EMA20 79243, ~0.28% extension)
    candles = []
    base_price = 79000.0
    base_time = 1700000000
    for i in range(35):
        price = base_price + (i * 10.0)
        candles.append(_make_candle(base_time + (i * 900), price - 5, price + 10, price - 10, price))

    # Standard low-conviction SHORT is blocked by bullish BTC
    res_low = BtcAnchorEngine.evaluate_btc_alignment("ETHUSD", "SHORT", candles, setup_score=65)
    assert res_low.is_allowed is False
    assert "BLOCKED BY BTC MACRO ANCHOR" in res_low.rejection_reason

    # High-conviction SHORT (Score 90) is PERMITTED
    res_high = BtcAnchorEngine.evaluate_btc_alignment("ETHUSD", "SHORT", candles, setup_score=90)
    assert res_high.is_allowed is True
    assert "High-conviction setup" in res_high.reason

    # Model 11 (Judas Swing) or Model 14 (SMT Divergence) is PERMITTED
    res_model11 = BtcAnchorEngine.evaluate_btc_alignment("ETHUSD", "SHORT", candles, setup_score=75, model_id="MODEL_11")
    assert res_model11.is_allowed is True
    assert "MODEL_11" in res_model11.reason
