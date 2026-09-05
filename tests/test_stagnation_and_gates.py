import pytest
import time
from market_data.models import MultiTimeframeContext, Candle
from strategy.confirmation_engine import ConfirmationEngine


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


def test_hard_gates_macro_trend_failure():
    # Long trade with Bearish 1H and Bearish 4H -> Hard Gate 1 must fail
    base_t = 1700000000
    candles_5m = [_make_candle(base_t + (i * 300), 100, 105, 95, 102, 2000.0) for i in range(25)]
    candles_15m = [_make_candle(base_t + (i * 900), 100, 105, 95, 102, 2000.0) for i in range(25)]
    mtf = MultiTimeframeContext(
        symbol="BTCUSD",
        timeframe="5m",
        trend_1h="Bearish",
        macro_bias_4h="Bearish",
        key_levels_daily=[]
    )
    res = ConfirmationEngine.evaluate(
        direction="LONG",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        mtf_context=mtf
    )
    assert res.hard_gates_passed is False
    assert res.is_qualified is False
    assert any("Hard Gate 1 Failed" in f for f in res.hard_gate_failures)


@pytest.mark.asyncio
async def test_velocity_stagnation_60m_breakeven(mock_trade_manager):
    tm = mock_trade_manager

    # Set active trade entered 65 minutes ago (3900 seconds ago)
    now_ts = int(time.time())
    entry_price = 100.0
    stop_price = 95.0
    tm.active_trade = {
        "setup_id": "test_stag_1",
        "coin": "SOLUSD",
        "direction": "LONG",
        "entry": entry_price,
        "stop_loss": stop_price,
        "original_stop": stop_price,
        "target_1": 110.0,
        "target_2": 120.0,
        "trade_status": "ACTIVE",
        "activated_timestamp": now_ts - 3900,
        "margin_used": 4500.0,
        "leverage": 6,
        "peak_favorable_price": 100.5,
        "be_moved": False,
        "partial_closed": False,
    }
    tm.db.set_active_trade(tm.active_trade)

    # Current price is 100.5 (only +0.1R, well under +0.5R threshold)
    await tm.update_price("SOLUSD", 100.5)

    # Stop Loss must have been ratcheted up to Breakeven
    assert tm.active_trade["be_moved"] is True
    assert tm.active_trade["stop_loss"] >= entry_price


@pytest.mark.asyncio
async def test_velocity_stagnation_90m_scratch_exit(mock_trade_manager):
    tm = mock_trade_manager

    # Set active trade entered 95 minutes ago (5700 seconds ago)
    now_ts = int(time.time())
    entry_price = 100.0
    stop_price = 95.0
    tm.active_trade = {
        "setup_id": "test_stag_2",
        "coin": "SOLUSD",
        "direction": "LONG",
        "entry": entry_price,
        "stop_loss": entry_price, # already BE
        "original_stop": stop_price,
        "target_1": 110.0,
        "target_2": 120.0,
        "trade_status": "ACTIVE",
        "activated_timestamp": now_ts - 5700,
        "margin_used": 4500.0,
        "leverage": 6,
        "peak_favorable_price": 100.5,
        "be_moved": True,
        "partial_closed": False,
    }
    tm.db.set_active_trade(tm.active_trade)

    # Current price is 100.1 (+0.02R, within +/- 0.25R sideways chop)
    await tm.update_price("SOLUSD", 100.1)

    # Trade must be scratch closed
    assert tm.active_trade is None
    assert tm.global_status in ("COOLDOWN", "WATCHING")
