import pytest
from config.settings import settings
from risk_engine.position_sizing import PositionSizer

def test_daily_loss_limit_is_160():
    assert settings.MAX_DAILY_LOSS == 160.0
    assert settings.MIN_REMAINING_DAILY_LOSS_QUOTA == 60.0

def test_dynamic_margin_scaling_full_conviction():
    # Setup with RR >= 2.0 gets full 100% margin (Rs. 4,200)
    res = PositionSizer.calculate_position(
        entry=100.0,
        stop_loss=98.0,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        target_rr=2.2
    )
    assert res.is_allowed is True
    assert res.required_margin == 4200.0

def test_dynamic_margin_scaling_lower_swing_high():
    # Setup with lower swing high (e.g. 1.8R) gets scaled margin
    res = PositionSizer.calculate_position(
        entry=100.0,
        stop_loss=98.0,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        leverage=6,
        target_rr=1.8
    )
    assert res.is_allowed is True
    # 1.8 / 2.0 = 0.90 -> 4200 * 0.90 = 3780.0
    assert res.required_margin == 3780.0
    assert res.required_margin < 4200.0

def test_daily_loss_enforcement_at_160():
    res = PositionSizer.calculate_position(
        entry=100.0,
        stop_loss=98.0,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        current_daily_loss=160.0,
        max_daily_loss=160.0
    )
    assert res.is_allowed is False
    assert 'Max daily loss reached' in res.rejection_reason

def test_remaining_quota_floor_at_60():
    # If daily loss is 105.0 on a 160 budget, remaining quota is 55.0 (<= 60 threshold) -> trade blocked!
    res = PositionSizer.calculate_position(
        entry=100.0,
        stop_loss=98.0,
        account_equity=4200.0,
        max_allowed_margin=4200.0,
        current_daily_loss=105.0,
        max_daily_loss=160.0
    )
    assert res.is_allowed is False
    assert 'Insufficient remaining daily loss quota' in res.rejection_reason
    assert '60.00' in res.rejection_reason

