import pytest
from risk_engine.position_sizing import PositionSizer


def test_position_sizing_margin_cap():
    """Validates position sizing and ₹250 max margin enforcement."""
    res = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        account_equity=3000.0,
        max_risk_pct=2.0,
        max_allowed_margin=250.0,
        leverage=10
    )

    assert res.is_allowed is True
    # Required margin must be capped at <= 250.0
    assert res.required_margin <= 250.0
    assert res.units > 0


def test_daily_loss_and_consecutive_losses_guard():
    """Validates that daily loss is active by default, while consecutive loss halts remain disabled."""
    # 1. By default, SPIDY DOES halt if daily loss exceeds MAX_DAILY_LOSS (420.0)
    res_daily_blocked = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        current_daily_loss=450.0,
        consecutive_losses=0
    )
    assert res_daily_blocked.is_allowed is False
    assert "daily loss" in res_daily_blocked.rejection_reason.lower()

    # 2. But consecutive losses do NOT halt trades by default (e.g. 5 consecutive losses allowed if daily loss within budget)
    res_consec_allowed = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        current_daily_loss=100.0,
        consecutive_losses=5
    )
    assert res_consec_allowed.is_allowed is True

    # 2. When explicit max_daily_loss is provided, it can be enforced
    res_daily = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        current_daily_loss=2000.0,
        max_daily_loss=500.0
    )
    assert res_daily.is_allowed is False
    assert "daily loss" in res_daily.rejection_reason.lower()

    # 3. When explicit max_consecutive_losses is provided, it can be enforced
    res_consec = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        consecutive_losses=3,
        max_consecutive_losses=3
    )
    assert res_consec.is_allowed is False
    assert "consecutive losses" in res_consec.rejection_reason.lower()
