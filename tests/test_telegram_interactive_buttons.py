import pytest
from unittest.mock import AsyncMock, patch
from telegram.notifier import get_trade_inline_keyboard, TelegramNotifier
from telegram.bot_listener import TelegramBotListener
from trade_manager.manager import TradeManager
from storage.database import Database


def test_trade_inline_keyboard_buttons():
    kb = get_trade_inline_keyboard()
    assert "inline_keyboard" in kb
    rows = kb["inline_keyboard"]
    assert len(rows) == 3

    # Row 1: Breakeven & Partial TP
    assert rows[0][0]["text"] == "🎯 Move SL to Breakeven"
    assert rows[0][0]["callback_data"] == "CMD_BE"
    assert rows[0][1]["text"] == "💰 Close 50% Partial TP"
    assert rows[0][1]["callback_data"] == "CMD_PARTIAL"

    # Row 2: Emergency Close & Instant Status
    assert rows[1][0]["text"] == "🛑 Emergency Close Trade"
    assert rows[1][0]["callback_data"] == "CMD_CLOSE"
    assert rows[1][1]["text"] == "⚡ Instant Status Check"
    assert rows[1][1]["callback_data"] == "CMD_STATUS"

    # Row 3: Daily Trade Journal
    assert rows[2][0]["text"] == "📖 Daily Trade Journal"
    assert rows[2][0]["callback_data"] == "CMD_JOURNAL"


@pytest.mark.asyncio
async def test_trade_manager_remote_actions(temp_db):
    tm = TradeManager(db=temp_db)
    
    # 1. No active trade -> returns False
    be_ok, _ = await tm.move_to_breakeven()
    assert be_ok is False
    part_ok, _ = await tm.close_partial()
    assert part_ok is False

    # 2. Inject active trade
    tm.active_trade = {
        "setup_id": "TEST_BTC_1",
        "coin": "BTCUSD",
        "direction": "LONG",
        "entry": 77000.0,
        "stop_loss": 76500.0,
        "target_1": 78000.0,
        "target_2": 78500.0,
        "rr": 2.5,
        "setup_score": 100,
        "trade_status": "ACTIVE",
        "margin_used": 250.0,
        "model_id": "MODEL_10",
        "model_name": "Institutional Sniper"
    }

    # Move to Breakeven
    be_ok, be_msg = await tm.move_to_breakeven()
    assert be_ok is True
    assert tm.active_trade["stop_loss"] == 77000.0
    assert tm.active_trade["be_moved"] is True

    # Close 50% partial
    part_ok, part_msg = await tm.close_partial(0.50)
    assert part_ok is True
    assert tm.active_trade["margin_used"] == 125.0
    assert tm.active_trade["partial_closed"] is True

    # Emergency Close
    close_ok, close_msg = await tm.emergency_close("Test Emergency Close")
    assert close_ok is True
    assert tm.active_trade is None
    assert tm.global_status == "WATCHING"


@pytest.mark.asyncio
async def test_telegram_listener_routes_callbacks(temp_db):
    tm = TradeManager(db=temp_db)
    listener = TelegramBotListener(trade_manager=tm, bot_token="MOCK_TOKEN", chat_id="12345")

    # Mock the internal network calls
    listener._answer_callback = AsyncMock()
    listener._send_reply = AsyncMock()

    # Call CMD_STATUS
    await listener._handle_callback("cb_1", "CMD_STATUS")
    assert listener._answer_callback.called
    assert listener._send_reply.called

    await listener.close()
