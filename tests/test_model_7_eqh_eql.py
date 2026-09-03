import pytest
from structure.swings import SwingPoint
from structure.liquidity import LiquidityEngine, EqualHighLowPool


def test_equal_highs_and_lows_detection():
    """Validates that swings within 0.18% difference are classified as Equal Highs / Lows."""
    swings = [
        SwingPoint(point_type="HIGH", price=2400.0, index=5, time=100, is_major=True),
        SwingPoint(point_type="LOW", price=2370.0, index=8, time=120, is_major=True),
        SwingPoint(point_type="HIGH", price=2401.5, index=12, time=150, is_major=True),
        SwingPoint(point_type="LOW", price=2370.5, index=15, time=180, is_major=True),
    ]

    pools = LiquidityEngine.find_equal_highs_lows(swings, tolerance_pct=0.20)
    assert len(pools) >= 2
    eqh = [p for p in pools if p.pool_type == "EQH"]
    eql = [p for p in pools if p.pool_type == "EQL"]

    assert len(eqh) >= 1
    assert len(eql) >= 1
    assert eqh[0].level == pytest.approx(2400.75, 0.1)
    assert eql[0].level == pytest.approx(2370.25, 0.1)
