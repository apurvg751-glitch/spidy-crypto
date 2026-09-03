import pytest
from risk_engine.position_sizing import PositionSizer


def test_position_sizing_margin_cap():
    """Validates position sizing and ₹250 max margin enforcement."""
    res = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        account_equity=10000.0,
        max_risk_pct=2.0,
        max_allowed_margin=250.0,
        leverage=10
    )

    assert res.is_allowed is True
    # Required margin must be capped at <= 250.0
    assert res.required_margin <= 250.0
    assert res.units > 0


def test_daily_loss_and_consecutive_losses_guard():
    """Validates that excessive daily loss or consecutive losses block new trades."""
    # Exceeded daily loss
    res_daily = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        current_daily_loss=2000.0 # > 1750.0 max daily loss
    )
    assert res_daily.is_allowed is False
    assert "daily loss" in res_daily.rejection_reason.lower()

    # Exceeded consecutive losses
    res_consec = PositionSizer.calculate_position(
        entry=2400.0,
        stop_loss=2380.0,
        consecutive_losses=3 # >= 3 max consecutive losses
    )
    assert res_consec.is_allowed is False
    assert "consecutive losses" in res_consec.rejection_reason.lower()
