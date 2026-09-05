import pytest
from datetime import datetime, timezone
from market_data.session_filter import SessionFilterEngine


def test_session_filter_london_open():
    # 08:30 UTC -> London Open
    dt = datetime(2026, 9, 5, 8, 30, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "LONDON_OPEN"
    assert res.is_peak_institutional is True
    assert res.min_confirmations_required == 4
    assert res.min_score_required == 70


def test_session_filter_new_york_open():
    # 14:00 UTC -> New York Open
    dt = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "NEW_YORK_OPEN"
    assert res.is_peak_institutional is True
    assert res.min_confirmations_required == 4


def test_session_filter_off_peak():
    # 02:00 UTC -> Off-Peak
    dt = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    res = SessionFilterEngine.evaluate_session(int(dt.timestamp()))
    assert res.session_name == "OFF_PEAK_CHOP"
    assert res.is_peak_institutional is False
    assert res.min_confirmations_required == 5
    assert res.min_score_required == 80
