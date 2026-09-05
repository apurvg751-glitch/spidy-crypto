import pytest
from unittest.mock import AsyncMock
from trade_manager.manager import TradeManager
from storage.database import Database


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_partial.db"
    return Database(db_path=str(db_file))


@pytest.mark.asyncio
async def test_automated_1r_partial_secures_40_percent(temp_db):
    """
    Verifies that when price hits +1.0R:
    1. 40% of trade is automatically banked in profit.
    2. Active margin is reduced to 60% (e.g. 3000 -> 1800).
    3. Stop Loss is automatically moved to Breakeven + fee buffer.
    4. Subsequent price ticks do not duplicate partial take.
    """
    tm = TradeManager(db=temp_db)
    tm.telegram.send_message = AsyncMock(return_value=True)
    tm.telegram.send_trade_lifecycle_update = AsyncMock(return_value=True)
    tm.telegram.send_partial_profit_secured = AsyncMock(return_value=True)

    # Setup active LONG trade: Entry 100.0, Stop 90.0 (Risk = 10.0), TP1 115.0, TP2 130.0
    tm.active_trade = {
        "setup_id": "TEST_PARTIAL_1R",
        "coin": "AVAXUSD",
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 90.0,
        "original_stop": 90.0,
        "target_1": 115.0,
        "target_2": 130.0,
        "trade_status": "ACTIVE",
        "margin_used": 3000.0,
        "leverage": 6,
        "model_id": "MODEL_1",
        "model_name": "Test Model",
        "partial_closed": False
    }
    tm.global_status = "ACTIVE"
    temp_db.set_active_trade(tm.active_trade)

    # 1. Price at 105.0 (+0.5R) -> Partial should NOT trigger yet
    await tm.update_price("AVAXUSD", 105.0)
    assert tm.active_trade["partial_closed"] is False
    assert tm.active_trade["margin_used"] == 3000.0

    # 2. Price hits 110.0 (+1.0R exactly) -> Automated 40% partial MUST trigger!
    await tm.update_price("AVAXUSD", 110.0)
    assert tm.active_trade["partial_closed"] is True
    assert tm.active_trade["partial_pct"] == 0.40
    # 60% of 3000 = 1800 remaining margin
    assert tm.active_trade["margin_used"] == 1800.0
    # Stop Loss should be moved to at least Breakeven (>= 100.0)
    assert tm.active_trade["stop_loss"] >= 100.0
    assert tm.active_trade["be_moved"] is True
    # Realized partial profit calculation: 1200 closed margin * 6x leverage * 10% move = ₹720
    assert tm.active_trade.get("realized_partial_pnl") is not None
    assert tm.active_trade["realized_partial_pnl"] > 0
    # Confirm Telegram alert was dispatched
    assert tm.telegram.send_partial_profit_secured.called

    # 3. Subsequent price move at 112.0 (+1.2R) -> Must NOT re-trigger partial
    tm.telegram.send_partial_profit_secured.reset_mock()
    await tm.update_price("AVAXUSD", 112.0)
    assert tm.telegram.send_partial_profit_secured.called is False
    assert tm.active_trade["margin_used"] == 1800.0


@pytest.mark.asyncio
async def test_automated_1r_partial_short_trade(temp_db):
    """
    Verifies that automated 1.0R partial works equally well on SHORT trades.
    Entry: 100.0, Stop: 110.0 (Risk = 10.0). +1.0R is price at 90.0.
    """
    tm = TradeManager(db=temp_db)
    tm.telegram.send_message = AsyncMock(return_value=True)
    tm.telegram.send_trade_lifecycle_update = AsyncMock(return_value=True)
    tm.telegram.send_partial_profit_secured = AsyncMock(return_value=True)

    tm.active_trade = {
        "setup_id": "TEST_SHORT_1R",
        "coin": "ETHUSD",
        "direction": "SHORT",
        "entry": 100.0,
        "stop_loss": 110.0,
        "original_stop": 110.0,
        "target_1": 85.0,
        "target_2": 70.0,
        "trade_status": "ACTIVE",
        "margin_used": 3000.0,
        "leverage": 6,
        "model_id": "MODEL_2",
        "model_name": "Test Short",
        "partial_closed": False
    }
    tm.global_status = "ACTIVE"
    temp_db.set_active_trade(tm.active_trade)

    # Price at 90.0 (+1.0R for SHORT)
    await tm.update_price("ETHUSD", 90.0)
    assert tm.active_trade["partial_closed"] is True
    assert tm.active_trade["margin_used"] == 1800.0
    assert tm.active_trade["stop_loss"] <= 100.0
    assert tm.active_trade["be_moved"] is True
    assert tm.active_trade["realized_partial_pnl"] > 0


@pytest.mark.asyncio
async def test_trade_close_includes_realized_partial_pnl(temp_db):
    """
    Verifies that when a trade with 40% partial profit closed exits,
    its final recorded PnL correctly sums the 40% realized profit + runner exit PnL.
    """
    tm = TradeManager(db=temp_db)
    tm.telegram.send_message = AsyncMock(return_value=True)
    tm.telegram.send_trade_lifecycle_update = AsyncMock(return_value=True)
    tm.telegram.send_partial_profit_secured = AsyncMock(return_value=True)

    tm.active_trade = {
        "setup_id": "TEST_FULL_EXIT",
        "coin": "AVAXUSD",
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 90.0,
        "original_stop": 90.0,
        "target_1": 115.0,
        "target_2": 130.0,
        "trade_status": "ACTIVE",
        "margin_used": 3000.0,
        "leverage": 6,
        "model_id": "MODEL_1",
        "model_name": "Test Model",
        "partial_closed": False,
        "rr": 2.0,
        "setup_score": 85
    }
    temp_db.save_setup({
        "id": "TEST_FULL_EXIT",
        "coin": "AVAXUSD",
        "direction": "LONG",
        "detection_timestamp": 123456,
        "entry": 100.0,
        "stop_loss": 90.0,
        "target_1": 115.0,
        "target_2": 130.0,
        "rr": 2.0,
        "setup_score": 85
    }, is_selected=True, trade_status="ACTIVE")
    tm.global_status = "ACTIVE"
    temp_db.set_active_trade(tm.active_trade)

    # 1. Trigger +1.0R partial at 110.0
    await tm.update_price("AVAXUSD", 110.0)
    assert tm.active_trade["partial_closed"] is True
    partial_pnl = tm.active_trade["realized_partial_pnl"]
    assert partial_pnl > 0

    # 2. Price pulls back to Breakeven stop loss (100.5)
    # The remaining 60% runner exits at breakeven
    await tm._close_trade("COMPLETED", 100.5, "Exited at Breakeven Stop")
    assert tm.active_trade is None

    # Check setup in DB to verify final PnL recorded contains the partial profit!
    history = temp_db.get_history(limit=5)
    closed = [s for s in history if s["id"] == "TEST_FULL_EXIT"]
    assert len(closed) == 1
    assert closed[0]["pnl"] >= partial_pnl

