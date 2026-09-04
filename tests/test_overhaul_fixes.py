import pytest
import time
from unittest.mock import AsyncMock
from config.precision import get_symbol_precision, get_symbol_tick_size, round_price, format_price
from config.settings import settings
from risk_engine.position_sizing import PositionSizer
from structure.trailing_engine import TrailingStopEngine
from structure.target_snapper import TargetSnapper
from structure.swings import SwingPoint
from structure.bos_choch import BosChochEngine
from backtesting.metrics import BacktestTrade, calculate_backtest_metrics
from trade_manager.manager import TradeManager
from telegram.notifier import TelegramNotifier
from tests.conftest import make_candle


def test_symbol_precision_and_formatting():
    """Validates precision and price formatting for all 6 active symbols."""
    # 1. BTCUSD: 1 decimal, tick 0.1
    assert get_symbol_precision("BTCUSD") == 1
    assert get_symbol_tick_size("BTCUSD") == 0.1
    assert round_price("BTCUSD", 79499.14) == 79499.1
    assert format_price("BTCUSD", 79499.14) == "$79,499.1"

    # 2. ETHUSD: 2 decimals, tick 0.01
    assert get_symbol_precision("ETHUSD") == 2
    assert get_symbol_tick_size("ETHUSD") == 0.01
    assert round_price("ETHUSD", 2650.126) == 2650.13
    assert format_price("ETHUSD", 2650.126) == "$2,650.13"

    # 3. SOLUSD: 2 decimals, tick 0.01
    assert get_symbol_precision("SOLUSD") == 2
    assert round_price("SOLUSD", 175.459) == 175.46

    # 4. BNBUSD: 2 decimals, tick 0.01
    assert get_symbol_precision("BNBUSD") == 2
    assert round_price("BNBUSD", 582.341) == 582.34

    # 5. AVAXUSD: 3 decimals, tick 0.001
    assert get_symbol_precision("AVAXUSD") == 3
    assert get_symbol_tick_size("AVAXUSD") == 0.001
    assert round_price("AVAXUSD", 25.1234) == 25.123
    assert format_price("AVAXUSD", 25.1234) == "$25.123"

    # 6. XRPUSD: 4 decimals, tick 0.0001
    assert get_symbol_precision("XRPUSD") == 4
    assert get_symbol_tick_size("XRPUSD") == 0.0001
    assert round_price("XRPUSD", 0.54321) == 0.5432
    assert format_price("XRPUSD", 0.54321) == "$0.5432"


def test_target_snapper_subdollar_precision():
    """Ensures target snapper preserves precision on low-dollar coins (e.g. XRP)."""
    candles = [
        make_candle(100 * i, 0.54 + i * 0.001, 0.545 + i * 0.001, 0.535 + i * 0.001, 0.542 + i * 0.001)
        for i in range(25)
    ]

    snapped = TargetSnapper.snap_targets(
        symbol="XRPUSD",
        direction="LONG",
        entry=0.5500,
        stop_loss=0.5300,
        candles_15m=candles,
        atr=0.015
    )
    assert snapped.target_1 > 0.55
    assert snapped.target_2 > snapped.target_1
    target_str = str(snapped.target_1)
    if "." in target_str:
        assert len(target_str.split(".")[1]) <= 4


def test_position_sizing_currency_peg():
    """Validates position size converts INR notional to USD correctly."""
    margin_inr = 3000.0
    leverage = 6
    btc_entry = 70000.0

    res_btc = PositionSizer.calculate_position(
        entry=btc_entry,
        stop_loss=69000.0,
        max_allowed_margin=margin_inr,
        leverage=leverage
    )
    assert res_btc.is_allowed is True
    assert res_btc.notional_value == 18000.0
    assert res_btc.required_margin == 3000.0

    expected_notional_usd = (margin_inr * leverage) / settings.USD_INR_RATE
    expected_btc_units = expected_notional_usd / btc_entry

    assert abs(res_btc.units - expected_btc_units) < 1e-4
    assert res_btc.units < 0.01  # Currency converted properly

    # XRP test
    xrp_entry = 0.50
    res_xrp = PositionSizer.calculate_position(
        entry=xrp_entry,
        stop_loss=0.48,
        max_allowed_margin=margin_inr,
        leverage=leverage
    )
    assert res_xrp.is_allowed is True
    expected_xrp_units = expected_notional_usd / xrp_entry
    assert pytest.approx(res_xrp.units, rel=1e-2) == expected_xrp_units


def test_trailing_stop_breathing_room():
    """Validates trailing stop ratchet provides adequate breathing room and doesn't stop out prematurely."""
    entry = 80000.0
    initial_stop = 79000.0
    risk = 1000.0
    atr = 500.0
    current_price = 82100.0

    trail = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=entry,
        original_stop=initial_stop,
        current_stop=initial_stop,
        current_price=current_price,
        peak_favorable_price=current_price,
        atr=atr,
        symbol="BTCUSD"
    )

    assert trail.stop_moved is True
    distance_from_peak = current_price - trail.new_stop
    assert distance_from_peak >= 400.0
    assert trail.new_stop > entry


@pytest.mark.asyncio
async def test_trademanager_preserves_original_stop_and_r_multiple(temp_db):
    """Verifies TradeManager preserves original_stop and calculates accurate R-multiple on exit."""
    mock_telegram = AsyncMock(spec=TelegramNotifier)
    mock_telegram.send_trade_lifecycle_update = AsyncMock(return_value=True)
    tm = TradeManager(db=temp_db, telegram=mock_telegram)

    entry = 80000.0
    orig_stop = 79000.0
    t1 = 81500.0
    t2 = 82500.0

    temp_db.save_setup({
        "id": "TEST_TRAIL_1",
        "coin": "BTCUSD",
        "direction": "LONG",
        "detection_timestamp": int(time.time()),
        "entry": entry,
        "stop_loss": orig_stop,
        "target_1": t1,
        "target_2": t2,
        "rr": 2.5,
        "setup_score": 95
    }, is_selected=True, trade_status="ACTIVE")

    tm.active_trade = {
        "setup_id": "TEST_TRAIL_1",
        "coin": "BTCUSD",
        "direction": "LONG",
        "entry": entry,
        "stop_loss": orig_stop,
        "original_stop": orig_stop,
        "target_1": t1,
        "target_2": t2,
        "rr": 2.5,
        "setup_score": 95,
        "trade_status": "ACTIVE",
        "margin_used": 3000.0,
        "leverage": 6,
        "position_units": 0.00257,
        "model_id": "MODEL_10",
        "model_name": "Institutional Sniper",
        "peak_favorable_price": entry,
        "peak_adverse_price": entry
    }

    # Price moves up to 81800 (+1.8R), triggering trailing stop ratchet
    await tm.update_price("BTCUSD", 81800.0)

    assert tm.active_trade["stop_loss"] > entry
    assert tm.active_trade["original_stop"] == orig_stop

    # Price pulls back and touches trailing stop
    ratcheted_stop = tm.active_trade["stop_loss"]
    await tm.update_price("BTCUSD", ratcheted_stop - 10.0)

    assert tm.active_trade is None
    history = temp_db.get_history()
    matched = [h for h in history if h["id"] == "TEST_TRAIL_1"]
    assert len(matched) == 1
    record = matched[0]
    assert record["trade_status"] == "COMPLETED"
    assert record["achieved_r"] > 0.5
    assert record["pnl"] > 0


def test_bos_forward_candle_index():
    """Verifies BOS detection identifies true break candle index, not latest candle."""
    candles = [
        make_candle(1, 100, 102, 99, 101),
        make_candle(2, 101, 105, 100, 104),
        make_candle(3, 104, 103, 101, 102),
        make_candle(4, 102, 104, 101, 103),
        # Candle 5 closes above 105.0 swing high
        make_candle(5, 103, 108, 102, 107),
        # Candle 6 continues consolidation
        make_candle(6, 107, 107.5, 106.5, 107.0)
    ]
    swings = [
        SwingPoint(index=1, price=105.0, point_type="HIGH", time=2, structure_label="HH")
    ]

    event = BosChochEngine.detect(candles, swings, search_bars=4, trend_bias="Bullish")
    assert event.detected is True
    assert event.event_type == "BOS"
    assert event.broken_level == 105.0
    # Break candle is candle index 4 (the 5th candle), NOT candle index 5 (the 6th candle)
    assert event.candle_index == 4


def test_backtesting_breakeven_metrics():
    """Verifies breakeven trades are recorded as won=False and do not inflate win rate."""
    be_trade = BacktestTrade(
        id="BE_1", coin="BTCUSD", model_id="MODEL_1", direction="LONG",
        entry_time=100, exit_time=200, entry_price=80000, exit_price=80000,
        stop_loss=79000, target_1=81500, target_2=82500, expected_rr=2.5,
        achieved_r=0.0, pnl=0.0, won=False, setup_score=85, confirmations_count=5,
        mfe=1.2, mae=0.1, exit_reason="BREAKEVEN"
    )

    metrics = calculate_backtest_metrics([be_trade])
    assert metrics.total_trades == 1
    assert metrics.wins == 0
    assert metrics.losses == 1
    assert metrics.win_rate == 0.0


def test_database_schema_and_active_trade_roundtrip(temp_db):
    """Verifies that all new overhaul columns in active_trade table persist and roundtrip cleanly."""
    trade_data = {
        "setup_id": "TEST_DB_PERSIST",
        "coin": "AVAXUSD",
        "direction": "LONG",
        "entry": 25.123,
        "stop_loss": 24.500,
        "target_1": 26.000,
        "target_2": 26.500,
        "rr": 2.2,
        "setup_score": 92,
        "trade_status": "ACTIVE",
        "position_units": 8.188,
        "margin_used": 3000.0,
        "leverage": 6,
        "original_stop": 24.500,
        "grade": "A+",
        "be_moved": True,
        "t1_hit": False,
        "partial_closed": False
    }

    temp_db.set_active_trade(trade_data)
    retrieved = temp_db.get_active_trade()

    assert retrieved is not None
    assert retrieved["coin"] == "AVAXUSD"
    assert retrieved["position_units"] == 8.188
    assert retrieved["margin_used"] == 3000.0
    assert retrieved["leverage"] == 6
    assert retrieved["original_stop"] == 24.500
    assert retrieved["grade"] == "A+"
    assert retrieved["be_moved"] == 1 or retrieved["be_moved"] is True


def test_telegram_exit_reason_headers_english():
    """Verifies that Telegram lifecycle notifications output clear English exit reason headers."""
    from telegram.formatter import format_lifecycle_alert

    # 1. Trailing Stop
    trail_msg = format_lifecycle_alert(
        coin="BTCUSD",
        direction="LONG",
        status="COMPLETED",
        price=79695.5,
        details="Trailing Stop Loss Hit at $79,696.00 (Profit Secured)",
        achieved_r=1.0,
        pnl=1800.0,
        entry=79499.0,
        stop_loss=79160.0
    )
    assert "TRAILING STOP LOSS HIT (PROFIT SECURED 🔒)" in trail_msg
    assert "Realized PnL: +₹1,800.00 🟢" in trail_msg

    # 2. Original Stop Loss
    stop_msg = format_lifecycle_alert(
        coin="BTCUSD",
        direction="LONG",
        status="STOPPED",
        price=79160.0,
        details="Original Stop Loss Hit at $79,160.00 (Risk Protection)",
        achieved_r=-1.0,
        pnl=-1800.0,
        entry=79499.0,
        stop_loss=79160.0
    )
    assert "STOP LOSS HIT (RISK PROTECTED 🛡️)" in stop_msg
    assert "Realized PnL: -₹1,800.00 🔴" in stop_msg

    # 3. Manual Close
    manual_msg = format_lifecycle_alert(
        coin="BTCUSD",
        direction="LONG",
        status="CANCELLED",
        price=79550.0,
        details="Manually Closed via Telegram Button",
        achieved_r=0.2,
        pnl=360.0,
        entry=79499.0,
        stop_loss=79160.0
    )
    assert "MANUALLY CLOSED VIA TELEGRAM BUTTON ✋" in manual_msg


def test_rvol_calculation_in_models():
    """Verifies that calculate_rvol uses 20-period baseline correctly."""
    from indicators.volume import calculate_rvol

    candles = [
        make_candle(100 * i, 100, 102, 99, 101, volume=1000.0)
        for i in range(25)
    ]
    # Current bar has 2x average volume
    candles[-1].volume = 2000.0

    rvol = calculate_rvol(candles)
    assert pytest.approx(rvol, rel=1e-2) == 2.0

