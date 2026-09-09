import pytest
from risk_engine.position_sizing import PositionSizer
from config.settings import settings


def test_dynamic_margin_at_full_band_4500():
    """Verifies that at ₹4,500 equity, full margin is allocated up to max allowed margin."""
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.0,
        account_equity=4500.0,
        max_allowed_margin=4500.0,
        min_allowed_margin=3000.0,
        leverage=6,
        current_daily_loss=0.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    assert res.required_margin == 4500.0
    assert res.units > 0


def test_dynamic_margin_within_band_3800():
    """Verifies that at ₹3,800 equity, Spidy downscales margin to 95% (₹3,610) to provide fee cushion."""
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.0,
        account_equity=3800.0,
        max_allowed_margin=4500.0,
        min_allowed_margin=3000.0,
        leverage=6,
        current_daily_loss=0.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    assert res.required_margin == 3610.0  # 3800 * 0.95
    assert res.units > 0


def test_dynamic_margin_at_lower_boundary_3000():
    """Verifies that at ₹3,000 minimum boundary, trade is allowed with 95% buffer."""
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.0,
        account_equity=3000.0,
        max_allowed_margin=4500.0,
        min_allowed_margin=3000.0,
        leverage=6,
        current_daily_loss=0.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    assert res.required_margin == 2850.0  # 3000 * 0.95
    assert res.units > 0


def test_dynamic_margin_below_floor_rejected():
    """Verifies that if equity drops below ₹3,000 (e.g. ₹2,900), trade is rejected safely."""
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.0,
        account_equity=2900.0,
        max_allowed_margin=4500.0,
        min_allowed_margin=3000.0,
        leverage=6,
        current_daily_loss=0.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is False
    assert "below minimum allowed margin threshold" in res.rejection_reason.lower()


def test_dynamic_margin_combined_with_quota_clamping():
    """
    Verifies that when equity is in the allowed band (₹4,400) but an intraday loss of ₹80 has occurred,
    risk is clamped to <= ₹80.00 while maintaining margin feasibility.
    """
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.0,  # 1.0 USD stop distance
        account_equity=4400.0,
        max_allowed_margin=4500.0,
        min_allowed_margin=3000.0,
        leverage=6,
        current_daily_loss=80.0,
        max_daily_loss=160.0,  # Remaining quota = ₹80.00 (> ₹60.00 floor)
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    assert res.risk_amount <= 80.0
    assert res.required_margin <= 4400.0
