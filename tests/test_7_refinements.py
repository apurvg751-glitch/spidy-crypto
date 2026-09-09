import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from config.settings import settings
from risk_engine.risk_calculator import RiskEngine
from structure.target_snapper import TargetSnapper
from structure.trailing_engine import TrailingStopEngine
from market_data.models import Candle
from market_data.delta_execution import DeltaExecutionClient
from trade_manager.manager import TradeManager
from storage.database import Database


def make_candle(ts: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=ts, open=o, high=h, low=l, close=c, volume=100.0, is_closed=True)


# 1. Micro-Wick Cushion on Structural SL
def test_micro_wick_cushion():
    # Long setup: extreme swing low is 100.0, entry is 105.0, ATR is 2.0
    levels_long = RiskEngine.calculate_levels(
        direction="LONG",
        current_price=105.0,
        extreme_level=100.0,
        atr=2.0,
        grade="A+"
    )
    # Standard buffer: max(2.0 * 0.35 = 0.70, 105.0 * 0.0010 = 0.105) = 0.70
    # Stop should be extreme_level - buffer = 100.0 - 0.70 = 99.30 (cushion below 100.0)
    assert levels_long.stop_loss < 100.0
    assert levels_long.stop_loss == 99.30

    # Short setup: extreme swing high is 105.0, entry is 100.0, ATR is 2.0
    levels_short = RiskEngine.calculate_levels(
        direction="SHORT",
        current_price=100.0,
        extreme_level=105.0,
        atr=2.0,
        grade="A+"
    )
    # Stop should be extreme_level + buffer = 105.0 + 0.70 = 105.70 (cushion above 105.0)
    assert levels_short.stop_loss > 105.0
    assert levels_short.stop_loss == 105.70


# 2. Target Snapping Front-Run Buffer
def test_target_snapper_front_run_buffer():
    candles_15m = [
        make_candle(i * 900, 100.0, 110.0, 99.0, 101.0) for i in range(25)
    ]
    # For LONG: physical swing high is 110.0. Snapped target should be slightly beneath 110.0
    snapped_long = TargetSnapper.snap_targets(
        direction="LONG",
        entry=100.0,
        stop_loss=98.0,
        candles_15m=candles_15m,
        atr=2.0,
        min_rr=1.6,
        symbol="SOLUSD",
        apply_front_run=True
    )
    # 110.0 * 0.9992 = 109.912
    assert snapped_long.target_1 < 110.0
    assert snapped_long.target_1 <= 109.92

    # For SHORT: physical swing low is 90.0. Snapped target should be slightly above 90.0
    candles_short = [
        make_candle(i * 900, 100.0, 101.0, 90.0, 99.0) for i in range(25)
    ]
    snapped_short = TargetSnapper.snap_targets(
        direction="SHORT",
        entry=100.0,
        stop_loss=102.0,
        candles_15m=candles_short,
        atr=2.0,
        min_rr=1.6,
        symbol="SOLUSD",
        apply_front_run=True
    )
    # 90.0 * 1.0008 = 90.072
    assert snapped_short.target_1 > 90.0
    assert snapped_short.target_1 >= 90.07


# 3. Fee-Protected Breakeven Floor
def test_fee_protected_breakeven_floor():
    # Achieved R = 0.9 (>= 0.8 trigger for BE)
    # Entry = 1000.0, risk = 5.0 (tight 0.5% risk)
    # Standard 0.05 * risk = 0.25 (only 0.025%, which would NOT cover 0.05% Delta taker fee)
    # New fee_buf = max(0.05 * 5.0, 1000.0 * 0.0008) = max(0.25, 0.80) = 0.80
    trail_res = TrailingStopEngine.evaluate_trail(
        direction="LONG",
        entry=1000.0,
        original_stop=995.0,
        current_stop=995.0,
        current_price=1004.5,  # +0.9R
        peak_favorable_price=1004.5,
        atr=5.0,
        symbol="ETHUSD"
    )
    assert trail_res.stop_moved is True
    # Stop should be entry + 0.80 = 1000.80
    assert trail_res.new_stop >= 1000.80


# 4. Pre-Flight Spread Guard
@pytest.mark.asyncio
async def test_pre_flight_spread_guard():
    client = DeltaExecutionClient(api_key="mock", api_secret="mock")

    # Mock acceptable spread: bid=100.0, ask=100.05 (spread = 0.05% = 5 bps <= 12 bps)
    mock_resp_ok = MagicMock()
    mock_resp_ok.status_code = 200
    mock_resp_ok.json.return_value = {
        "result": {
            "quotes": {"best_bid": "100.0", "best_ask": "100.05"},
            "mark_price": "100.02"
        }
    }

    with patch.object(client.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp_ok
        is_ok, bps, pct = await client.check_spread("SOLUSD", max_spread_bps=12.0)
        assert is_ok is True
        assert bps <= 12.0

        # Mock wide spread: bid=100.0, ask=100.25 (spread = 0.25% = 25 bps > 12 bps)
        mock_resp_wide = MagicMock()
        mock_resp_wide.status_code = 200
        mock_resp_wide.json.return_value = {
            "result": {
                "quotes": {"best_bid": "100.0", "best_ask": "100.25"},
                "mark_price": "100.10"
            }
        }
        mock_get.return_value = mock_resp_wide
        is_ok, bps, pct = await client.check_spread("SOLUSD", max_spread_bps=12.0)
        assert is_ok is False
        assert bps > 12.0

    await client.close()


# 5. 35-Minute Stagnation Advisory Alert
@pytest.mark.asyncio
async def test_35_minute_stagnation_advisory(tmp_path):
    db = Database(db_path=str(tmp_path / "test_stag.db"))
    tm = TradeManager(db=db)
    tm.telegram = MagicMock()
    tm.telegram.send_stagnation_alert = AsyncMock(return_value=True)

    # Active trade open for 40 minutes (2400 seconds), hovering at +0.2R (under 0.5R)
    now_ts = 1700000000
    tm.active_trade = {
        "setup_id": "test_1",
        "coin": "SOLUSD",
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 98.0,
        "original_stop": 98.0,
        "target_1": 104.0,
        "target_2": 106.0,
        "current_price": 100.4,  # +0.2R
        "activated_timestamp": now_ts - 2400,
        "partial_closed": False,
        "trade_status": "ACTIVE"
    }

    with patch("time.time", return_value=now_ts):
        await tm.update_price("SOLUSD", 100.4)
        assert tm.active_trade.get("stagnation_alert_sent") is True
        tm.telegram.send_stagnation_alert.assert_called_once()
        args = tm.telegram.send_stagnation_alert.call_args[1]
        assert args["symbol"] == "SOLUSD"
        assert args["duration_mins"] == 40
        assert args["current_r"] == 0.20


# 6. Midnight Rollover Telegram Notification
@pytest.mark.asyncio
async def test_midnight_rollover_telegram_dispatch(tmp_path):
    db = Database(db_path=str(tmp_path / "test_rollover.db"))
    tm = TradeManager(db=db)
    tm.telegram = MagicMock()
    tm.telegram.send_midnight_rollover_recap = AsyncMock(return_value=True)

    tm.current_daily_date = "2026-09-06"
    tm.current_daily_loss = 141.0

    # Call rollover check
    res = tm.check_daily_loss_reset()
    assert res is True
    assert tm.current_daily_loss == 0.0
    await asyncio.sleep(0.01)  # allow spawned task to run
    tm.telegram.send_midnight_rollover_recap.assert_called_once()
    args = tm.telegram.send_midnight_rollover_recap.call_args[1]
    assert args["old_loss"] == 141.0
    assert args["max_daily_loss"] == getattr(settings, "MAX_DAILY_LOSS", 160.0)
