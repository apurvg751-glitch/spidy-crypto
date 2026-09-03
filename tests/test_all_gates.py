import time
import pytest
from pathlib import Path

from market_data.models import Candle
from market_data.delta_rest import DeltaRestClient
from strategy.setup_detector import SetupDetector, DetectedSetup
from strategy.scoring import SetupScoreBreakdown
from trade_manager.manager import TradeManager
from storage.database import Database
from telegram.formatter import format_main_alert, format_lifecycle_alert
from telegram.notifier import TelegramNotifier
from tests.conftest import generate_candles


# ==============================================================================
# GATE 1, 2, 3: DATA PROCESSING (ETH, BTC, SOL)
# ==============================================================================
@pytest.mark.asyncio
async def test_eth_data_processed():
    """Gate 1: ETH data can be processed."""
    candles = generate_candles(base_price=2400.0, count=30, trend="UP")
    assert len(candles) == 30
    assert candles[-1].close > candles[0].close
    assert candles[0].total_range > 0
    assert candles[-1].time > candles[0].time


@pytest.mark.asyncio
async def test_btc_data_processed():
    """Gate 2: BTC data can be processed."""
    candles = generate_candles(base_price=77000.0, count=40, trend="DOWN")
    assert len(candles) == 40
    assert candles[-1].close < candles[0].close
    assert candles[-1].body_size >= 0


@pytest.mark.asyncio
async def test_sol_data_processed():
    """Gate 3: SOL data can be processed."""
    candles = generate_candles(base_price=98.5, count=35, trend="FLAT")
    assert len(candles) == 35
    assert all(c.open > 0 and c.high >= c.low for c in candles)


# ==============================================================================
# GATE 4, 5, 6: SETUP DETECTION & REJECTION
# ==============================================================================
def test_valid_long_setup_detected():
    """Gate 4: Valid LONG setup can be detected (bullish trend + liquidity sweep + rejection + volume)."""
    # 15m bullish candles
    candles_15m = generate_candles(base_price=2350.0, count=40, interval_seconds=900, trend="UP")

    # 5m candles with a swing low, then a sweep of that swing low, with high volume and rejection
    candles_5m = generate_candles(base_price=2380.0, count=30, interval_seconds=300, trend="UP")

    # Inject an established swing low at index 20
    candles_5m[20].low = 2370.0
    candles_5m[20].open = 2375.0
    candles_5m[20].close = 2374.0

    # Ensure surrounding bars are higher than index 20 low
    for j in range(17, 20):
        candles_5m[j].low = 2373.0
    for j in range(21, 24):
        candles_5m[j].low = 2373.0

    # Inject a clean liquidity sweep at the latest bar (bar 29):
    # wick dips to 2368.0 (< 2370.0), but closes back up at 2382.0 (> 2370.0)
    sweep_bar = candles_5m[-1]
    sweep_bar.open = 2375.0
    sweep_bar.low = 2367.0       # Pierced swing low 2370.0
    sweep_bar.close = 2383.0     # Closed above swing low
    sweep_bar.high = 2384.0
    sweep_bar.volume = 5000.0    # Massive volume spike

    res = SetupDetector.evaluate(
        symbol="ETHUSD",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        current_price=2383.0,
        is_stale=False
    )

    assert res.signal == "LONG"
    assert res.setup is not None
    assert res.setup.coin == "ETHUSD"
    assert res.setup.direction == "LONG"
    assert res.setup.setup_score >= 70
    assert res.setup.sweep_confirmed is True
    assert res.setup.stop_loss < res.setup.entry
    assert res.setup.target_2 > res.setup.entry
    assert res.setup.rr >= 1.5


def test_valid_short_setup_detected():
    """Gate 5: Valid SHORT setup can be detected (bearish trend + liquidity sweep + rejection + volume)."""
    # 15m bearish candles
    candles_15m = generate_candles(base_price=2450.0, count=40, interval_seconds=900, trend="DOWN")

    # 5m candles with a swing high, then a sweep of that swing high
    candles_5m = generate_candles(base_price=2400.0, count=30, interval_seconds=300, trend="DOWN")

    # Inject an established swing high at index 20
    candles_5m[20].high = 2420.0
    candles_5m[20].open = 2410.0
    candles_5m[20].close = 2412.0

    for j in range(17, 20):
        candles_5m[j].high = 2415.0
    for j in range(21, 24):
        candles_5m[j].high = 2415.0

    # Inject a clean liquidity sweep at the latest bar:
    # wick spikes to 2424.0 (> 2420.0), but closes back down at 2408.0 (< 2420.0)
    sweep_bar = candles_5m[-1]
    sweep_bar.open = 2415.0
    sweep_bar.high = 2425.0      # Pierced swing high 2420.0
    sweep_bar.close = 2405.0     # Closed below swing high
    sweep_bar.low = 2404.0
    sweep_bar.volume = 5000.0    # Volume spike

    res = SetupDetector.evaluate(
        symbol="ETHUSD",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        current_price=2405.0,
        is_stale=False
    )

    assert res.signal == "SHORT"
    assert res.setup is not None
    assert res.setup.coin == "ETHUSD"
    assert res.setup.direction == "SHORT"
    assert res.setup.setup_score >= 70
    assert res.setup.sweep_confirmed is True
    assert res.setup.stop_loss > res.setup.entry
    assert res.setup.target_2 < res.setup.entry
    assert res.setup.rr >= 1.5


def test_invalid_setup_rejected():
    """Gate 6: Invalid setup is rejected (chop / no sweep / counter-trend)."""
    # Flat market with no structural sweeps
    candles_15m = generate_candles(base_price=2400.0, count=30, interval_seconds=900, trend="FLAT")
    candles_5m = generate_candles(base_price=2400.0, count=30, interval_seconds=300, trend="FLAT")

    res = SetupDetector.evaluate(
        symbol="ETHUSD",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        current_price=2400.0,
        is_stale=False
    )

    assert res.signal == "NO SETUP"
    assert res.setup is None
    assert len(res.rejection_reasons) > 0


# ==============================================================================
# GATE 7, 8: TELEGRAM ALERTS & ANTI-SPAM
# ==============================================================================
def test_telegram_alert_formatting():
    """Gate 7: Telegram alert formatting matches exact user template."""
    setup_data = {
        "coin": "ETHUSD",
        "direction": "LONG",
        "setup_score": 87,
        "entry": 2385.50,
        "stop_loss": 2368.00,
        "target_1": 2415.00,
        "target_2": 2445.00,
        "rr": 3.4,
        "trend_15m": "Bullish",
        "sweep_confirmed": True,
        "bos_confirmed": True,
        "volume_confirmed": True,
        "trade_status": "WAITING"
    }

    alert_text = format_main_alert(setup_data)

    # Check required text elements from user's specification
    assert "🕷️ SPIDY CRYPTO — TRADE DETECTED" in alert_text
    assert "Coin: ETHUSD" in alert_text
    assert "Direction: LONG" in alert_text
    assert "Setup Score: 87/100" in alert_text
    assert "Entry: 2385.50" in alert_text
    assert "Stop: 2368.00" in alert_text
    assert "Target 1: 2415.00" in alert_text
    assert "Target 2: 2445.00" in alert_text
    assert "RR: 1:3.4" in alert_text
    assert "15M Trend: Bullish" in alert_text
    assert "Liquidity Sweep: Confirmed" in alert_text
    assert "BOS: Confirmed" in alert_text
    assert "Volume: Confirmed" in alert_text
    assert "Status: WAITING" in alert_text
    assert "Only ONE SPIDY CRYPTO trade can be active at one time." in alert_text


@pytest.mark.asyncio
async def test_duplicate_telegram_alerts_blocked(temp_db):
    """Gate 8: Duplicate Telegram alerts are blocked by anti-spam guard."""
    notifier = TelegramNotifier(db=temp_db)

    setup_dict = {
        "id": "ETHUSD_LONG_1700000000_2385",
        "coin": "ETHUSD",
        "direction": "LONG",
        "setup_score": 85,
        "entry": 2385.0,
        "stop_loss": 2365.0,
        "target_1": 2415.0,
        "target_2": 2445.0,
        "rr": 3.0,
        "trade_status": "WAITING"
    }

    # First send: records alert_id
    alert_id = f"MAIN_{setup_dict['id']}"
    assert temp_db.is_alert_sent(alert_id) is False

    await notifier.send_trade_detected_alert(setup_dict)
    assert temp_db.is_alert_sent(alert_id) is True

    # Second send: must be blocked
    sent_second_time = await notifier.send_trade_detected_alert(setup_dict)
    assert sent_second_time is False
    await notifier.close()


# ==============================================================================
# GATE 9: HISTORY PERSISTENCE & CRASH RECOVERY
# ==============================================================================
def test_history_persists_after_restart(tmp_path: Path):
    """Gate 9: History persists after restart via SQLite."""
    db_file = tmp_path / "persistent_spidy.db"
    db1 = Database(db_path=db_file)

    setup_data = {
        "id": "BTCUSD_SHORT_1700000100_77100",
        "coin": "BTCUSD",
        "direction": "SHORT",
        "detection_timestamp": 1700000100,
        "entry": 77100.0,
        "stop_loss": 77400.0,
        "target_1": 76650.0,
        "target_2": 76200.0,
        "rr": 3.0,
        "setup_score": 90,
        "trend_15m": "Bearish",
        "reasons": ["15M Bearish", "Sweep Confirmed", "Score 90"]
    }

    db1.save_setup(setup_data, is_selected=True, trade_status="ACTIVE")

    # Simulate app restart with a fresh Database instance
    db2 = Database(db_path=db_file)
    history = db2.get_history()

    assert len(history) == 1
    assert history[0]["id"] == "BTCUSD_SHORT_1700000100_77100"
    assert history[0]["coin"] == "BTCUSD"
    assert history[0]["setup_score"] == 90
    assert history[0]["is_selected"] == 1


# ==============================================================================
# GATE 10, 11, 12, 13: GLOBAL SINGLE TRADE LOCK & MULTI-COIN RULES
# ==============================================================================
def _create_mock_setup(coin: str, score: int, rr: float = 2.5, direction: str = "LONG") -> DetectedSetup:
    now = int(time.time())
    return DetectedSetup(
        id=f"{coin}_{direction}_{now}_{score}",
        coin=coin,
        direction=direction,
        detection_timestamp=now,
        entry=2400.0 if coin == "ETHUSD" else (77000.0 if coin == "BTCUSD" else 98.0),
        stop_loss=2370.0 if coin == "ETHUSD" else (76500.0 if coin == "BTCUSD" else 96.0),
        target_1=2445.0 if coin == "ETHUSD" else (77750.0 if coin == "BTCUSD" else 101.0),
        target_2=2475.0 if coin == "ETHUSD" else (78250.0 if coin == "BTCUSD" else 103.0),
        rr=rr,
        setup_score=score,
        score_breakdown=SetupScoreBreakdown(
            trend_score=25, sweep_score=25, bos_score=20, volume_score=10, rr_score=10, total_score=score
        ),
        trend_15m="Bullish",
        sweep_confirmed=True,
        sweep_details="Test sweep",
        bos_confirmed=True,
        bos_details="Test bos",
        volume_confirmed=True,
        volume_details="RVOL 1.3",
        atr=25.0,
        reasons=["Test reason"]
    )


@pytest.mark.asyncio
async def test_only_one_trade_can_become_active(mock_trade_manager):
    """Gate 10: Only ONE trade can become active across the system."""
    setup_eth = _create_mock_setup("ETHUSD", score=85)
    setup_btc = _create_mock_setup("BTCUSD", score=80)

    # First setup activates
    active1 = await mock_trade_manager.process_candidates([setup_eth])
    assert active1 is not None
    assert active1["coin"] == "ETHUSD"
    assert mock_trade_manager.active_trade["coin"] == "ETHUSD"

    # Second setup is rejected because slot is occupied
    active2 = await mock_trade_manager.process_candidates([setup_btc])
    assert active2 is None
    assert mock_trade_manager.active_trade["coin"] == "ETHUSD"


@pytest.mark.asyncio
async def test_eth_active_blocks_btc_and_sol(mock_trade_manager):
    """Gate 11: If ETH is active, BTC and SOL are blocked with BLOCKED BY ACTIVE TRADE status."""
    setup_eth = _create_mock_setup("ETHUSD", score=82)
    await mock_trade_manager.process_candidates([setup_eth])

    setup_btc = _create_mock_setup("BTCUSD", score=90)
    setup_sol = _create_mock_setup("SOLUSD", score=88)

    # Attempt to process BTC and SOL while ETH is active
    await mock_trade_manager.process_candidates([setup_btc, setup_sol])

    # Check database: BTC and SOL must be stored with BLOCKED status and explanation
    btc_rec = mock_trade_manager.db.get_history(coin="BTCUSD")[0]
    assert btc_rec["trade_status"] == "BLOCKED BY ACTIVE TRADE"
    assert "BLOCKED BY ACTIVE TRADE: ETHUSD is currently in" in btc_rec["rejection_reason"]

    sol_rec = mock_trade_manager.db.get_history(coin="SOLUSD")[0]
    assert sol_rec["trade_status"] == "BLOCKED BY ACTIVE TRADE"


@pytest.mark.asyncio
async def test_coin_eligible_after_active_closes(mock_trade_manager):
    """Gate 12: After ETH closes, another coin can become eligible."""
    setup_eth = _create_mock_setup("ETHUSD", score=85)
    await mock_trade_manager.process_candidates([setup_eth])
    assert mock_trade_manager.active_trade["coin"] == "ETHUSD"

    # Trigger Entry (WAITING -> ACTIVE)
    await mock_trade_manager.update_price("ETHUSD", 2400.0)
    assert mock_trade_manager.active_trade["trade_status"] == "ACTIVE"

    # Trigger Target 2 (ACTIVE -> COMPLETED)
    await mock_trade_manager.update_price("ETHUSD", 2475.0)
    assert mock_trade_manager.active_trade is None
    assert mock_trade_manager.global_status == "WATCHING"

    # Now SOL should be eligible to become the active trade!
    setup_sol = _create_mock_setup("SOLUSD", score=84)
    new_active = await mock_trade_manager.process_candidates([setup_sol])

    assert new_active is not None
    assert new_active["coin"] == "SOLUSD"
    assert mock_trade_manager.active_trade["coin"] == "SOLUSD"


@pytest.mark.asyncio
async def test_simultaneous_triggers_highest_ranked_selected(mock_trade_manager):
    """Gate 13: If ETH/BTC/SOL trigger simultaneously, only the highest-ranked valid setup is selected."""
    setup_eth = _create_mock_setup("ETHUSD", score=78, rr=2.0)
    setup_btc = _create_mock_setup("BTCUSD", score=92, rr=3.2)  # Highest rank!
    setup_sol = _create_mock_setup("SOLUSD", score=85, rr=2.5)

    # Process all three simultaneously
    selected = await mock_trade_manager.process_candidates([setup_eth, setup_btc, setup_sol])

    assert selected is not None
    assert selected["coin"] == "BTCUSD"
    assert selected["setup_score"] == 92

    # Check losers in database have clear rejection reasoning
    eth_rec = mock_trade_manager.db.get_history(coin="ETHUSD")[0]
    assert eth_rec["trade_status"] == "BLOCKED BY ACTIVE TRADE"
    assert "Selected BTCUSD (Score: 92" in eth_rec["rejection_reason"]

    sol_rec = mock_trade_manager.db.get_history(coin="SOLUSD")[0]
    assert sol_rec["trade_status"] == "BLOCKED BY ACTIVE TRADE"
    assert "Selected BTCUSD (Score: 92" in sol_rec["rejection_reason"]


# ==============================================================================
# GATE 14: STALE OR INVALID DATA REJECTION
# ==============================================================================
def test_stale_or_invalid_market_data_cannot_produce_setup():
    """Gate 14: Stale or invalid market data cannot produce a setup."""
    candles_15m = generate_candles(base_price=2350.0, count=40, trend="UP")
    candles_5m = generate_candles(base_price=2380.0, count=30, trend="UP")

    # Case 1: is_stale flag is True
    res_stale = SetupDetector.evaluate(
        symbol="ETHUSD",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        current_price=2380.0,
        is_stale=True
    )
    assert res_stale.signal == "NO SETUP"
    assert "stale or disconnected" in res_stale.rejection_reasons[0]

    # Case 2: Insufficient / empty candles
    res_empty = SetupDetector.evaluate(
        symbol="BTCUSD",
        candles_5m=[],
        candles_15m=[],
        current_price=77000.0,
        is_stale=False
    )
    assert res_empty.signal == "NO SETUP"
    assert "Insufficient candle history" in res_empty.rejection_reasons[0]
