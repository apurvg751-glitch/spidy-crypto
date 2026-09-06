import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from telegram.chart_generator import generate_trade_chart, generate_symbol_analysis_chart
from telegram.formatter import format_trade_progress_bar, format_hud_telemetry, format_daily_executive_brief
from telegram.notifier import TelegramNotifier, get_hud_inline_keyboard, get_trade_inline_keyboard
from telegram.bot_listener import TelegramBotListener
from trade_manager.manager import TradeManager
from storage.database import Database
from config.settings import settings


def test_chart_generator_with_htf_white_line():
    """Validates that trade charts and symbol snapshots render with HTF White Line overlays."""
    # 1. Trade chart with ⚪ White Line (Institutional Origin)
    chart_png = generate_trade_chart(
        symbol="BTCUSD",
        direction="LONG",
        entry=64200.0,
        stop_loss=63800.0,
        target_1=64900.0,
        target_2=65400.0,
        candles=None,
        htf_walls=[63750.0, 65600.0]
    )
    assert isinstance(chart_png, bytes)
    assert len(chart_png) > 1000
    assert chart_png.startswith(b"\x89PNG")

    # 2. On-demand symbol analysis chart with ⚪ White Line
    sym_png = generate_symbol_analysis_chart(
        symbol="ETHUSD",
        current_price=2520.0,
        candles=None,
        htf_walls=[2480.0]
    )
    assert isinstance(sym_png, bytes)
    assert len(sym_png) > 1000
    assert sym_png.startswith(b"\x89PNG")


def test_emoji_progress_bar_calculation():
    """Validates neon emoji progress bar for profit, drawdown, and target hits."""
    # Long in profit (50% to TP1)
    bar_profit = format_trade_progress_bar(
        entry=100.0, target_1=110.0, stop_loss=95.0,
        current_price=105.0, direction="LONG", achieved_r=1.0
    )
    assert "🟩" in bar_profit
    assert "50.0%" in bar_profit or "50" in bar_profit
    assert "+1.00R" in bar_profit

    # Long in drawdown (moving towards SL)
    bar_dd = format_trade_progress_bar(
        entry=100.0, target_1=110.0, stop_loss=95.0,
        current_price=98.0, direction="LONG", achieved_r=-0.4
    )
    assert "🟥" in bar_dd
    assert "-0.40R" in bar_dd

    # Target 1 Hit
    bar_hit = format_trade_progress_bar(
        entry=100.0, target_1=110.0, stop_loss=95.0,
        current_price=110.5, direction="LONG", achieved_r=2.1
    )
    assert "TP1" in bar_hit
    assert "🟩" * 10 in bar_hit


def test_hud_telemetry_and_keyboard():
    """Validates master HUD interactive keyboard and telemetry message structure."""
    kb = get_hud_inline_keyboard()
    assert "inline_keyboard" in kb
    rows = kb["inline_keyboard"]
    assert len(rows) == 4

    # Row 1: Breakeven & 50% Partial
    assert rows[0][0]["text"] == "🎯 Breakeven"
    assert rows[0][0]["callback_data"] == "CMD_BE"
    assert rows[0][1]["text"] == "💰 50% Partial"
    assert rows[0][1]["callback_data"] == "CMD_PARTIAL"

    # Row 2: Instant Check Up & View Chart
    assert rows[1][0]["text"] == "⚡ Instant Check Up"
    assert rows[1][0]["callback_data"] == "CMD_STATUS"
    assert rows[1][1]["text"] == "📈 View Chart"
    assert rows[1][1]["callback_data"] == "CMD_CHART"

    # Row 3: Emergency Exit & Scan All
    assert rows[2][0]["text"] == "🛑 Emergency Exit"
    assert rows[2][0]["callback_data"] == "CMD_CLOSE"
    assert rows[2][1]["text"] == "⚡ Scan (9 Models)"
    assert rows[2][1]["callback_data"] == "CMD_SCAN"

    # Row 4: Refresh HUD & Daily Journal
    assert rows[3][0]["text"] == "🔄 Refresh HUD"
    assert rows[3][0]["callback_data"] == "CMD_HUD_REFRESH"
    assert rows[3][1]["text"] == "📖 Daily Journal"
    assert rows[3][1]["callback_data"] == "CMD_JOURNAL"

    hud_text = format_hud_telemetry(
        active_trade=None,
        live_prices={"BTCUSD": 64000.0, "ETHUSD": 2500.0, "SOLUSD": 138.0, "XRPUSD": 0.58, "BNBUSD": 540.0, "AVAXUSD": 24.5},
        daily_loss_info={"current_daily_loss": 0.0, "max_daily_loss": 420.0, "daily_loss_remaining": 420.0}
    )
    assert "SPIDY CRYPTO 2.0 — MASTER CONTROL HUD" in hud_text
    assert "₹420.00" in hud_text
    assert "XRPUSD" in hud_text


def test_daily_executive_brief_formatting():
    """Validates 11:59 PM IST Daily Executive Briefing formatting and loss refresh note."""
    sample_data = {
        "decided_trades": 2,
        "wins": 2,
        "losses": 0,
        "scratches": 0,
        "win_rate": 100.0,
        "total_r": 3.8,
        "total_pnl": 239.4
    }
    brief = format_daily_executive_brief(sample_data, current_daily_loss=0.0, max_daily_loss=420.0)
    assert "11:59 PM IST DAILY EXECUTIVE BRIEF" in brief
    assert "100.0%" in brief
    assert "+3.80R" in brief
    assert "REFRESHED" in brief


@pytest.mark.asyncio
async def test_notifier_auto_chart_on_active(tmp_path):
    """Verifies that send_trade_lifecycle_update dispatches chart snapshot on ACTIVE trade."""
    db = Database(str(tmp_path / "test.db"))
    notifier = TelegramNotifier(bot_token="test_token", chat_id="12345", db=db)
    notifier.send_photo = AsyncMock(return_value=True)

    await notifier.send_trade_lifecycle_update(
        coin="ETHUSD",
        direction="LONG",
        status="ACTIVE",
        price=2500.0,
        setup_id="test_setup_1",
        entry=2500.0,
        stop_loss=2480.0,
        target_1=2532.0,
        target_2=2550.0,
        htf_walls=[2475.0]
    )

    notifier.send_photo.assert_called_once()
    call_kwargs = notifier.send_photo.call_args.kwargs
    assert isinstance(call_kwargs["photo_bytes"], bytes)
    assert "ACTIVE" in call_kwargs["caption"]
    await notifier.close()


@pytest.mark.asyncio
async def test_bot_listener_hud_and_chart_commands(tmp_path):
    """Verifies bot listener routing for /hud and /chart commands."""
    db = Database(str(tmp_path / "test.db"))
    tm = TradeManager(db=db)
    listener = TelegramBotListener(trade_manager=tm, bot_token="test_token", chat_id="12345")
    listener._send_reply = AsyncMock(return_value=True)
    listener._send_chart_reply = AsyncMock(return_value=True)
    listener._send_hud_reply = AsyncMock(return_value=True)

    # Test /hud
    update_hud = {"message": {"text": "/hud", "chat": {"id": 12345}}}
    await listener._process_update(update_hud)
    listener._send_hud_reply.assert_called_once_with(12345)

    # Test /chart btc
    update_chart = {"message": {"text": "/chart btc", "chat": {"id": 12345}}}
    await listener._process_update(update_chart)
    listener._send_chart_reply.assert_called_once_with(12345, requested_symbol="BTC")

    await listener.close()
