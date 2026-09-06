"""
Tests for Multi-Timeframe Institutional Barrier Detection.
Validates that 1H/4H institutional displacement origins (supply/demand walls)
are correctly identified and used to cap targets and block trades.
"""
import pytest
from market_data.models import Candle
from structure.barrier_engine import BarrierEngine, BarrierValidationResult
from structure.target_snapper import TargetSnapper, SnappedTargets


def make_candle(time_sec: int, o: float, h: float, l: float, c: float, vol: float = 100.0) -> Candle:
    return Candle(symbol="ETHUSD", time=time_sec, open=o, high=h, low=l, close=c, volume=vol)


def build_normal_15m(n: int = 20, base: float = 2500.0) -> list[Candle]:
    """Build simple 15m candles for testing — no major barriers."""
    candles = []
    for i in range(n):
        o = base + (i * 2)
        h = o + 10
        l = o - 10
        c = o + 5
        candles.append(make_candle(i * 900, o, h, l, c))
    return candles


def build_htf_candles_with_institutional_drop(
    n: int = 24,
    base: float = 2600.0,
    drop_at: int = 18,
    drop_open: float = 2700.0,
    drop_close: float = 2580.0,
    drop_high: float = 2710.0,
    drop_low: float = 2575.0
) -> list[Candle]:
    """Build 1H candles with one massive bearish institutional displacement candle at drop_at index."""
    candles = []
    for i in range(n):
        if i == drop_at:
            # INSTITUTIONAL BEARISH DISPLACEMENT: body > 65%, expansion > 1.15x
            candles.append(make_candle(i * 3600, drop_open, drop_high, drop_low, drop_close, vol=500.0))
        else:
            o = base + (i * 3)
            h = o + 15
            l = o - 15
            c = o + 2
            candles.append(make_candle(i * 3600, o, h, l, c))
    return candles


def build_htf_candles_with_institutional_surge(
    n: int = 24,
    base: float = 2400.0,
    surge_at: int = 18,
    surge_open: float = 2350.0,
    surge_close: float = 2500.0,
    surge_high: float = 2505.0,
    surge_low: float = 2345.0
) -> list[Candle]:
    """Build 1H candles with one massive bullish institutional displacement candle."""
    candles = []
    for i in range(n):
        if i == surge_at:
            candles.append(make_candle(i * 3600, surge_open, surge_high, surge_low, surge_close, vol=500.0))
        else:
            o = base + (i * 3)
            h = o + 15
            l = o - 15
            c = o + 2
            candles.append(make_candle(i * 3600, o, h, l, c))
    return candles


# ============================================================
# BARRIER ENGINE — HTF WALL DETECTION TESTS
# ============================================================

class TestHTFInstitutionalWallDetection:
    def test_detects_bearish_supply_wall_on_1h(self):
        """1H bearish displacement creates a supply wall at the candle's open."""
        candles_1h = build_htf_candles_with_institutional_drop()
        supply, demand = BarrierEngine.detect_htf_institutional_walls(candles_1h, [])
        assert len(supply) >= 1
        assert 2700.0 in supply  # The open of the bearish displacement candle

    def test_detects_bullish_demand_wall_on_1h(self):
        """1H bullish displacement creates a demand wall at the candle's open."""
        candles_1h = build_htf_candles_with_institutional_surge()
        supply, demand = BarrierEngine.detect_htf_institutional_walls(candles_1h, [])
        assert len(demand) >= 1
        assert 2350.0 in demand  # The open of the bullish displacement candle

    def test_ignores_small_normal_candles(self):
        """Normal small candles should NOT be tagged as institutional walls."""
        candles_1h = build_normal_15m(24, base=2500.0)  # All tiny, normal candles
        supply, demand = BarrierEngine.detect_htf_institutional_walls(candles_1h, [])
        assert len(supply) == 0
        assert len(demand) == 0

    def test_empty_htf_candles_no_crash(self):
        """Empty 1H/4H candle lists should return no walls, no crash."""
        supply, demand = BarrierEngine.detect_htf_institutional_walls([], [])
        assert supply == []
        assert demand == []


class TestBarrierEngineHTFIntegration:
    def test_long_blocked_by_htf_supply_wall(self):
        """LONG should be blocked when price is too close to 1H supply wall overhead."""
        candles_15m = build_normal_15m(20, base=2680.0)
        candles_1h = build_htf_candles_with_institutional_drop(
            drop_open=2710.0, drop_close=2600.0, drop_high=2715.0, drop_low=2595.0
        )

        # Price at 2700 — only 10 pts (0.37%) below the supply wall at 2710
        res = BarrierEngine.validate_room_to_run(
            direction="LONG",
            current_price=2700.0,
            candles_15m=candles_15m,
            atr=15.0,
            candles_1h=candles_1h,
            candles_4h=[]
        )
        assert res.is_valid is False
        assert res.has_room is False
        assert "No Room to Run" in res.reason

    def test_short_blocked_by_htf_demand_wall(self):
        """SHORT should be blocked when price is too close to 1H demand wall below."""
        candles_15m = build_normal_15m(20, base=2360.0)
        candles_1h = build_htf_candles_with_institutional_surge(
            surge_open=2350.0, surge_close=2500.0, surge_high=2505.0, surge_low=2345.0
        )

        # Price at 2355 — only 5 pts (0.21%) above the demand wall at 2350
        res = BarrierEngine.validate_room_to_run(
            direction="SHORT",
            current_price=2355.0,
            candles_15m=candles_15m,
            atr=15.0,
            candles_1h=candles_1h,
            candles_4h=[]
        )
        assert res.is_valid is False
        assert res.has_room is False
        assert "No Room to Run" in res.reason

    def test_long_passes_with_adequate_htf_clearance(self):
        """LONG should pass when supply wall is far enough above."""
        candles_15m = build_normal_15m(20, base=2500.0)
        candles_1h = build_htf_candles_with_institutional_drop(
            drop_open=2700.0, drop_close=2600.0, drop_high=2710.0, drop_low=2595.0
        )

        # Price at 2550 — 150 pts (5.88%) below supply wall at 2700 — plenty of room
        res = BarrierEngine.validate_room_to_run(
            direction="LONG",
            current_price=2550.0,
            candles_15m=candles_15m,
            atr=15.0,
            candles_1h=candles_1h,
            candles_4h=[]
        )
        assert res.is_valid is True
        assert res.has_room is True

    def test_backward_compatible_without_htf_candles(self):
        """When no HTF candles are passed, old behavior is preserved."""
        candles_15m = build_normal_15m(20, base=2500.0)
        res = BarrierEngine.validate_room_to_run(
            direction="LONG",
            current_price=2520.0,
            candles_15m=candles_15m,
            atr=15.0
        )
        assert res.is_valid is True  # No HTF walls, should pass


# ============================================================
# TARGET SNAPPER — HTF CAP TESTS
# ============================================================

class TestTargetSnapperHTFCap:
    def test_long_tp_capped_below_htf_supply_wall(self):
        """For LONG: TP must be capped at 0.998x of the overhead supply wall."""
        # Build 15m candles with swing highs going up to 2600+ range (so natural TP would land above wall)
        candles_15m = []
        for i in range(24):
            o = 2500.0 + (i * 5)
            h = o + 30  # High swing highs up to ~2645
            l = o - 10
            c = o + 15
            candles_15m.append(make_candle(i * 900, o, h, l, c))

        # Place a supply wall at 2550 — well below the 15m swing highs
        candles_1h = build_htf_candles_with_institutional_drop(
            drop_open=2550.0, drop_close=2470.0, drop_high=2555.0, drop_low=2465.0
        )

        snapped = TargetSnapper.snap_targets(
            direction="LONG",
            entry=2520.0,
            stop_loss=2510.0,
            candles_15m=candles_15m,
            atr=15.0,
            min_rr=1.6,
            symbol="ETHUSD",
            candles_1h=candles_1h,
            candles_4h=[]
        )

        # TP1 must NOT exceed 0.998 * 2550.0 = 2544.9
        cap_level = 2550.0 * 0.998
        assert snapped.target_1 <= cap_level + 0.01
        assert snapped.htf_wall_cap_applied is True
        assert snapped.htf_wall_level == 2550.0

    def test_short_tp_capped_above_htf_demand_wall(self):
        """For SHORT: TP must be capped at 1.002x of the demand wall below."""
        # Build 15m candles with swing lows going down to ~2340 range (below the demand wall)
        candles_15m = []
        for i in range(24):
            o = 2430.0 - (i * 5)
            h = o + 10
            l = o - 30  # Low swing lows down to ~2315
            c = o - 15
            candles_15m.append(make_candle(i * 900, o, h, l, c))

        # Place a demand wall at 2390 — above the 15m swing lows
        candles_1h = build_htf_candles_with_institutional_surge(
            surge_open=2390.0, surge_close=2470.0, surge_high=2475.0, surge_low=2385.0
        )

        snapped = TargetSnapper.snap_targets(
            direction="SHORT",
            entry=2420.0,
            stop_loss=2430.0,
            candles_15m=candles_15m,
            atr=15.0,
            min_rr=1.6,
            symbol="ETHUSD",
            candles_1h=candles_1h,
            candles_4h=[]
        )

        # TP1 must NOT go below 1.002 * 2390.0 = 2394.78
        cap_level = 2390.0 * 1.002
        assert snapped.target_1 >= cap_level - 0.01
        assert snapped.htf_wall_cap_applied is True
        assert snapped.htf_wall_level == 2390.0

    def test_no_cap_when_no_htf_candles(self):
        """Without HTF candles, targets are determined only by 15m structure."""
        candles_15m = build_normal_15m(24, base=2500.0)

        snapped = TargetSnapper.snap_targets(
            direction="LONG",
            entry=2520.0,
            stop_loss=2510.0,
            candles_15m=candles_15m,
            atr=15.0,
            min_rr=1.6,
            symbol="ETHUSD"
        )

        assert snapped.htf_wall_cap_applied is False
        assert snapped.htf_wall_level is None

    def test_htf_cap_causes_rr_rejection(self):
        """If HTF wall is so close that capped TP gives < 1.6R, trade should fail minimum clearance."""
        candles_15m = build_normal_15m(24, base=2500.0)
        # Place supply wall extremely close — only 5 pts above entry
        candles_1h = build_htf_candles_with_institutional_drop(
            drop_open=2525.0, drop_close=2490.0, drop_high=2530.0, drop_low=2485.0
        )

        snapped = TargetSnapper.snap_targets(
            direction="LONG",
            entry=2520.0,
            stop_loss=2510.0,
            candles_15m=candles_15m,
            atr=15.0,
            min_rr=1.6,
            symbol="ETHUSD",
            candles_1h=candles_1h,
            candles_4h=[]
        )

        # With wall at 2525, cap = 2525 * 0.998 = 2519.95 — below entry!
        # RR will be < 1.6, so minimum clearance should be False
        assert snapped.has_minimum_clearance is False
