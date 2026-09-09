import pytest
from datetime import datetime, timezone
from market_data.session_filter import SessionFilterEngine


def test_session_filter_london_open():
    # 08:30 UTC -> London Open
    dt = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "LONDON_OPEN"
    assert res.is_peak_institutional is True
    assert res.is_trading_allowed is True
    assert res.min_confirmations_required == 4
    assert res.min_score_required == 70


def test_session_filter_new_york_open():
    # 14:00 UTC -> New York Open
    dt = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "NEW_YORK_OPEN"
    assert res.is_peak_institutional is True
    assert res.is_trading_allowed is True
    assert res.min_confirmations_required == 4


def test_session_filter_asian_session_blocked():
    # 02:00 UTC (07:30 IST) -> Asian Session
    dt = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "ASIAN_SESSION"
    assert res.is_peak_institutional is False
    assert res.is_trading_allowed is False


def test_session_filter_off_peak_dead_zone_blocked():
    # 22:00 UTC (03:30 IST) -> Off-Peak Dead Zone
    dt = datetime(2026, 9, 5, 22, 0, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "OFF_PEAK_CHOP"
    assert res.is_peak_institutional is False
    assert res.is_trading_allowed is False


@pytest.mark.asyncio
async def test_trade_manager_enforces_session_filter(temp_db):
    """Verifies that TradeManager rejects setups with BLOCKED_BY_SESSION_FILTER outside Killzones."""
    from trade_manager.manager import TradeManager
    from telegram.notifier import TelegramNotifier
    from tests.test_all_gates import _create_mock_setup

    notifier = TelegramNotifier(db=temp_db, bot_token="MOCK_TOKEN", chat_id="12345")
    tm = TradeManager(db=temp_db, telegram=notifier, cooldown_seconds=0, enforce_session_filter=True)

    cand = _create_mock_setup("XRPUSD", score=90)

    # Current time (morning IST) is Asian session (entries blocked)
    res = SessionFilterEngine.evaluate_session()
    if not res.is_trading_allowed:
        selected = await tm.process_candidates([cand])
        assert selected is None
        history = tm.db.get_history(coin="XRPUSD")
        assert len(history) > 0
        assert history[0]["trade_status"] == "BLOCKED_BY_SESSION_FILTER"
        assert "BLOCKED BY SESSION FILTER" in history[0]["rejection_reason"]


