import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from telegram.notifier import TelegramNotifier
from telegram.formatter import format_vip_channel_alert, format_vip_channel_lifecycle


def test_format_vip_channel_alert():
    setup = {
        "coin": "SOLUSD",
        "direction": "LONG",
        "grade": "A+",
        "entry": 103.50,
        "stop_loss": 102.80,
        "target_1": 104.75,
        "target_2": 105.25,
        "rr": 2.1,
        "macro_bias_4h": "Bullish",
        "trend_1h": "Bullish",
    }
    text = format_vip_channel_alert(setup)
    assert "SPIDY VIP INSTITUTIONAL SIGNAL" in text
    assert "#SOLUSD" in text
    assert "LONG" in text
    assert "$103.50" in text
    assert "$102.80" in text
    assert "$104.75" in text
    assert "GRADE A+" in text


def test_format_vip_channel_lifecycle_breakeven():
    text = format_vip_channel_lifecycle(
        coin="SOLUSD",
        direction="LONG",
        status="BREAKEVEN",
        price=103.95
    )
    assert "BREAKEVEN LOCKED" in text
    assert "0 RISK" in text
    assert "$103.95" in text


def test_format_vip_channel_lifecycle_tp1():
    text = format_vip_channel_lifecycle(
        coin="ETHUSD",
        direction="SHORT",
        status="TP1_HIT",
        price=2450.00,
        achieved_r=1.80
    )
    assert "TARGET 1 HIT!" in text
    assert "+1.80R" in text
    assert "$2450.00" in text


@pytest.mark.asyncio
async def test_notifier_broadcasts_to_channel():
    mock_db = MagicMock()
    mock_db.is_alert_sent.return_value = False

    notifier = TelegramNotifier(
        bot_token="TEST_BOT_TOKEN",
        chat_id="12345",
        channel_id="@TestSpidyChannel",
        db=mock_db
    )

    with patch.object(notifier, "send_photo", new_callable=AsyncMock) as mock_send_photo, \
         patch.object(notifier, "broadcast_to_channel", new_callable=AsyncMock) as mock_broadcast:

        mock_send_photo.return_value = True
        mock_broadcast.return_value = True

        setup = {
            "id": "setup_sol_1",
            "coin": "SOLUSD",
            "direction": "LONG",
            "entry": 103.50,
            "stop_loss": 102.80,
            "target_1": 104.75,
            "target_2": 105.25,
            "rr": 2.1
        }

        success = await notifier.send_trade_detected_alert(setup)
        assert success is True
        assert mock_send_photo.called
        assert mock_broadcast.called
        call_args = mock_broadcast.call_args[1]
        assert "SPIDY VIP INSTITUTIONAL SIGNAL" in call_args["text"]

    await notifier.close()
