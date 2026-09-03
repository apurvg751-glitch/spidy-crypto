import pytest
from market_data.models import Candle
from structure.swings import find_swings, classify_swings
from structure.market_structure import MarketStructureEngine
from structure.liquidity import LiquidityEngine
from structure.bos_choch import BosChochEngine
from structure.retest import RetestEngine
from structure.order_blocks import OrderBlockEngine
from structure.fvg import FvgEngine
from tests.conftest import make_candle


def test_swing_detection_and_classification():
    """Validates fractal swing detection and HH/HL/LH/LL classification."""
    candles = [
        make_candle(1, 100, 102, 99, 101),
        make_candle(2, 101, 103, 100, 102),
        make_candle(3, 102, 108, 101, 107), # High at index 2
        make_candle(4, 107, 105, 103, 104),
        make_candle(5, 104, 105, 102, 103),
        make_candle(6, 103, 104, 98, 99),   # Low at index 5
        make_candle(7, 99, 101, 98.5, 100),
        make_candle(8, 100, 102, 99, 101),
        make_candle(9, 101, 112, 100, 111), # Higher High at index 8
        make_candle(10, 111, 109, 107, 108),
        make_candle(11, 108, 107, 105, 106),
    ]

    swings = find_swings(candles, lookback=2)
    assert len(swings) >= 2

    highs = [s for s in swings if s.point_type == "HIGH"]
    assert len(highs) >= 1
    if len(highs) >= 2:
        assert highs[1].structure_label == "HH"


def test_liquidity_sweep_and_reclaim():
    """Validates liquidity sweep detection with lower wick penetration and close reclaim."""
    candles = [
        make_candle(1, 100, 102, 98, 101),
        make_candle(2, 101, 101, 95, 96),   # Swing low at 95.0
        make_candle(3, 96, 99, 95.5, 98),
        make_candle(4, 98, 101, 97, 100),
        make_candle(5, 100, 102, 99, 101),
        # Sweep bar: dips to 93.5 (below 95), closes at 96.5 (above 95), long lower wick
        make_candle(6, 97, 97.5, 93.5, 96.5),
    ]
    swings = find_swings(candles[:5], lookback=1)
    sweep = LiquidityEngine.detect_liquidity_sweep(candles, swings, search_bars=3)

    assert sweep.detected is True
    assert sweep.sweep_type == "BULLISH"
    assert sweep.sweep_level == 95.0
    assert sweep.reclaim_confirmed is True


def test_bos_and_choch_differentiation():
    """Validates BOS (continuation) vs CHoCH (reversal) structure breaks."""
    candles = [
        make_candle(1, 100, 102, 99, 101),
        make_candle(2, 101, 105, 100, 104), # Swing high at 105.0
        make_candle(3, 104, 103, 101, 102),
        make_candle(4, 102, 104, 101, 103),
        # Bullish break bar closing at 107.0
        make_candle(5, 103, 108, 102, 107),
    ]
    swings = find_swings(candles[:4], lookback=1)

    # In a bullish context -> BOS
    bos = BosChochEngine.detect(candles, swings, search_bars=2, trend_bias="Bullish")
    assert bos.detected is True
    assert bos.event_type == "BOS"
    assert bos.direction == "BULLISH"
    assert bos.broken_level == 105.0

    # In a bearish context -> CHoCH
    choch = BosChochEngine.detect(candles, swings, search_bars=2, trend_bias="Bearish")
    assert choch.detected is True
    assert choch.event_type == "CHOCH"
    assert choch.direction == "BULLISH"


def test_retest_engine():
    """Validates retest detection within ATR tolerance."""
    candles = [
        make_candle(1, 100, 105, 99, 104),
        make_candle(2, 104, 108, 103, 107), # Break bar at index 1 (level 105)
        # Retest bar: pulls back to 105.2 (near 105), closes at 106.0 with bottom wick
        make_candle(3, 107, 107, 105.1, 106.5),
    ]
    retest = RetestEngine.evaluate_retest(
        candles=candles,
        level=105.0,
        direction="LONG",
        break_bar_idx=1,
        atr=2.0,
        tolerance_atr=0.3
    )
    assert retest.detected is True
    assert retest.confirmed is True
    assert retest.direction == "BULLISH"


def test_order_block_and_fvg_engines():
    """Validates Order Block and Fair Value Gap identification."""
    # Bullish OB and FVG sequence:
    # bar 0: bearish setup candle (OB)
    # bar 1: massive green expansion candle
    # bar 2: green continuation (low higher than bar 0 high => FVG)
    c0 = make_candle(1, 100, 101, 98, 99)   # Bearish (high 101, low 98)
    c1 = make_candle(2, 99, 110, 98.5, 109) # Impulse
    c2 = make_candle(3, 109, 115, 104, 114) # Low 104 > c0 High 101 -> FVG [101, 104]

    candles = [c0, c1, c2]

    # Order Block detection
    obs = OrderBlockEngine.find_order_blocks("TEST", candles, lookback=5)
    assert len(obs) >= 1
    bull_ob = obs[0]
    assert bull_ob.direction == "BULLISH"
    assert bull_ob.top == 101.0
    assert bull_ob.bottom == 98.0
    assert bull_ob.is_fresh is True

    # FVG detection
    fvgs = FvgEngine.find_fvgs("TEST", candles, lookback=5)
    assert len(fvgs) >= 1
    fvg = fvgs[0]
    assert fvg.direction == "BULLISH"
    assert fvg.bottom == 101.0
    assert fvg.top == 104.0
