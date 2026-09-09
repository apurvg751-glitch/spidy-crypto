import pytest
from config.settings import settings
from risk_engine.position_sizing import PositionSizer


def test_tight_stop_scales_down_to_fit_80_quota():
    """
    Verifies that when remaining quota is above the floor (e.g. ₹80.00 after ₹80 loss on ₹160 limit),
    a setup with a valid structural stop scales down its position size so that
    total risk is strictly <= ₹80.00.
    """
    # SOL entry at 105.00, structural stop at 105.35 (stop distance $0.35)
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=105.35,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        current_daily_loss=80.0,
        max_daily_loss=160.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    # Risk must be strictly clamped to <= 80.00 INR
    assert res.risk_amount <= 80.01
    # Required margin should scale down from 4200 to accommodate smaller size
    assert res.required_margin < 4200.0
    assert res.units > 0


def test_wide_stop_rejected_when_exceeding_quota():
    """
    Verifies that if market structure requires a wide stop distance that exceeds
    the remaining quota even at the asset's minimum contract lot size, the trade
    is safely rejected to protect the daily limit.
    """
    # SOL entry at 105.00, wide structural stop at 115.00 ($10 stop distance)
    # Even 0.1 SOL * $10 * 87.5 = ₹87.50, which exceeds remaining ₹80 quota
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=115.0,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        current_daily_loss=80.0,
        max_daily_loss=160.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is False
    assert "exceeding allowed trade risk cap" in res.rejection_reason


def test_remaining_quota_at_or_below_floor_rejected():
    """
    Verifies that when remaining daily loss quota is <= ₹20.00, no trades are taken.
    """
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=105.35,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        current_daily_loss=280.0,
        max_daily_loss=300.0,  # Remaining quota = ₹20.00 <= ₹20.00 floor
        coin="SOLUSD"
    )
    assert res.is_allowed is False
    assert "Insufficient remaining daily loss quota" in res.rejection_reason


def test_full_quota_uses_standard_margin():
    """
    Verifies that during a fresh session with 0 loss, full ₹4,200 margin is allocated.
    """
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.50,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        current_daily_loss=0.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is True
    assert res.required_margin == 4200.0


def test_exhausted_quota_rejects_trade():
    """
    Verifies that if current daily loss has exhausted the quota (e.g. >= 201),
    trades are strictly rejected.
    """
    res = PositionSizer.calculate_position(
        entry=105.0,
        stop_loss=104.50,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        current_daily_loss=201.0,
        max_daily_loss=201.0,
        coin="SOLUSD"
    )

    assert res.is_allowed is False
    assert "Max daily loss reached" in res.rejection_reason
