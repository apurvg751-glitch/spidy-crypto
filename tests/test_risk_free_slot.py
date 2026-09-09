import time
import pytest
from unittest.mock import AsyncMock

from trade_manager.manager import TradeManager
from storage.database import Database
from telegram.notifier import TelegramNotifier
from strategy.setup_detector import DetectedSetup
from strategy.scoring import SetupScoreBreakdown


def _create_setup(coin: str, score: int = 85, direction: str = "LONG") -> DetectedSetup:
    now = int(time.time())
    entry_map = {
        "ETHUSD": (2400.0, 2370.0, 2445.0, 2475.0),
        "SOLUSD": (150.0, 145.0, 157.5, 162.5),
        "AVAXUSD": (30.0, 28.5, 32.25, 34.0),
        "XRPUSD": (0.60, 0.58, 0.63, 0.65),
    }
    entry, sl, tp1, tp2 = entry_map.get(coin, (100.0, 95.0, 107.5, 112.5))
    return DetectedSetup(
        id=f"{coin}_{direction}_{now}_{score}",
        coin=coin,
        direction=direction,
        detection_timestamp=now,
        entry=entry,
        stop_loss=sl,
        target_1=tp1,
        target_2=tp2,
        rr=2.5,
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
        atr=entry * 0.01,
        reasons=["Valid Institutional Setup"]
    )


@pytest.mark.asyncio
async def test_risk_free_slot_release_lifecycle(temp_db):
    """
    Verifies full lifecycle of Risk-Free Slot Release:
    1. ETH setup enters -> 1 trade with active downside risk.
    2. SOL setup attempted -> Blocked because ETH still has active risk.
    3. ETH moves to Breakeven (+0.8R or manual BE) -> Risk-free slot opens!
    4. SOL setup attempted -> Successfully entered as 2nd position.
    5. AVAX setup attempted -> Blocked because SOL has active risk and max concurrent slots reached.
    6. Independent trailing stop and clean multi-trade exit.
    """
    mock_notifier = AsyncMock(spec=TelegramNotifier)
    mock_notifier.send_trade_detected_alert = AsyncMock(return_value=True)
    mock_notifier.send_trade_lifecycle_update = AsyncMock(return_value=True)
    mock_notifier.send_partial_profit_secured = AsyncMock(return_value=True)

    tm = TradeManager(db=temp_db, telegram=mock_notifier, enforce_session_filter=False)

    # 1. Setup 1 (ETH) enters
    setup_eth = _create_setup("ETHUSD", score=85)
    trade_eth = await tm.process_candidates([setup_eth])
    assert trade_eth is not None
    assert trade_eth["coin"] == "ETHUSD"
    assert "ETHUSD" in tm.active_trades
    assert len(tm.active_trades) == 1

    summary1 = tm.get_current_status_summary()
    assert summary1["has_active_trade"] is True
    assert summary1["risk_slot_available"] is False
    assert summary1["risk_free_runner_active"] is False

    # 2. Setup 2 (SOL) attempted before ETH reaches Breakeven -> Blocked!
    setup_sol = _create_setup("SOLUSD", score=88)
    trade_sol_blocked = await tm.process_candidates([setup_sol])
    assert trade_sol_blocked is None
    assert "SOLUSD" not in tm.active_trades

    # Check history records rejection reason
    sol_hist = temp_db.get_history(coin="SOLUSD")
    assert len(sol_hist) > 0
    assert sol_hist[0]["trade_status"] == "BLOCKED BY ACTIVE TRADE"

    # 3. Trigger Entry and Breakeven on ETH (+0.8R)
    await tm.update_price("ETHUSD", 2400.0)  # WAITING -> ACTIVE
    assert tm.active_trades["ETHUSD"]["trade_status"] == "ACTIVE"

    # Move to Breakeven manually
    success, msg = await tm.move_to_breakeven(protect_fees=True, symbol="ETHUSD")
    assert success is True
    assert tm.active_trades["ETHUSD"]["be_moved"] is True

    # Now ETH carries $0 downside risk! Risk slot must be released
    summary2 = tm.get_current_status_summary()
    assert summary2["risk_slot_available"] is True
    assert summary2["risk_free_runner_active"] is True
    assert summary2["active_trades_count"] == 1

    # 4. Setup 2 (SOL) processed again -> Successfully entered as 2nd position!
    setup_sol2 = _create_setup("SOLUSD", score=90)
    trade_sol = await tm.process_candidates([setup_sol2])
    assert trade_sol is not None
    assert trade_sol["coin"] == "SOLUSD"
    assert len(tm.active_trades) == 2
    assert "ETHUSD" in tm.active_trades
    assert "SOLUSD" in tm.active_trades

    summary3 = tm.get_current_status_summary()
    # Now SOL carries active risk, so risk_slot_available must be False
    assert summary3["risk_slot_available"] is False
    assert summary3["active_trades_count"] == 2

    # 5. Setup 3 (AVAX) attempted -> Blocked because SOL has active risk and max concurrent slots = 2
    setup_avax = _create_setup("AVAXUSD", score=95)
    trade_avax_blocked = await tm.process_candidates([setup_avax])
    assert trade_avax_blocked is None
    assert "AVAXUSD" not in tm.active_trades

    # 6. SOL triggers entry
    await tm.update_price("SOLUSD", 150.0)
    assert tm.active_trades["SOLUSD"]["trade_status"] == "ACTIVE"

    # Close SOL at Target 2 (162.5) -> Only SOL finishes, ETH runner still active!
    await tm.update_price("SOLUSD", 162.5)
    assert "SOLUSD" not in tm.active_trades
    assert "ETHUSD" in tm.active_trades
    assert len(tm.active_trades) == 1
    assert tm.global_status == "ACTIVE"

    # Finally close ETH
    await tm.update_price("ETHUSD", 2475.0)  # Hits T2
    assert "ETHUSD" not in tm.active_trades
    assert len(tm.active_trades) == 0
    assert tm.global_status == "WATCHING"


@pytest.mark.asyncio
async def test_emergency_close_and_partial_with_two_active_trades(temp_db):
    """
    Tests targeted emergency close and partial execution when 2 positions are open.
    """
    mock_notifier = AsyncMock(spec=TelegramNotifier)
    mock_notifier.send_trade_detected_alert = AsyncMock(return_value=True)
    mock_notifier.send_trade_lifecycle_update = AsyncMock(return_value=True)
    mock_notifier.send_partial_profit_secured = AsyncMock(return_value=True)

    tm = TradeManager(db=temp_db, telegram=mock_notifier, enforce_session_filter=False)

    # Enter ETH & lock BE
    s_eth = _create_setup("ETHUSD", score=85)
    await tm.process_candidates([s_eth])
    await tm.update_price("ETHUSD", 2400.0)
    await tm.move_to_breakeven(protect_fees=True, symbol="ETHUSD")

    # Enter SOL as second trade
    s_sol = _create_setup("SOLUSD", score=90)
    await tm.process_candidates([s_sol])
    await tm.update_price("SOLUSD", 150.0)

    assert len(tm.active_trades) == 2

    # Partial close on SOL only
    ok_part, msg_part = await tm.close_partial(pct=0.50, symbol="SOLUSD")
    assert ok_part is True
    assert tm.active_trades["SOLUSD"]["partial_closed"] is True
    assert tm.active_trades["ETHUSD"].get("partial_closed") is not True

    # Emergency close on ETH only
    ok_close, msg_close = await tm.emergency_close(reason="Emergency Test", symbol="ETHUSD")
    assert ok_close is True
    assert "ETHUSD" not in tm.active_trades
    assert "SOLUSD" in tm.active_trades
    assert len(tm.active_trades) == 1

    # Emergency close all remaining
    ok_close_all, _ = await tm.emergency_close(reason="Close Remaining")
    assert ok_close_all is True
    assert len(tm.active_trades) == 0
    assert tm.global_status == "WATCHING"
