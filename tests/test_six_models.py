import pytest
from market_data.models import MarketState
from strategy.models import (
    Model1SweepReversal,
    Model2BosContinuation,
    Model3ObFvg,
    Model4ChochReversal,
    Model5BreakoutRetest,
    Model6TrendPullback,
    Model10InstitutionalSniper
)
from strategy.state_machine import SetupSequence
from tests.conftest import make_candle


def test_models_initialization_and_isolation():
    """Validates that models initialize independently with proper IDs and stats."""
    m1 = Model1SweepReversal()
    m2 = Model2BosContinuation()
    m3 = Model3ObFvg()
    m4 = Model4ChochReversal()
    m5 = Model5BreakoutRetest()
    m6 = Model6TrendPullback()
    m10 = Model10InstitutionalSniper()

    assert m1.model_id == "MODEL_1"
    assert m2.model_id == "MODEL_2"
    assert m3.model_id == "MODEL_3"
    assert m4.model_id == "MODEL_4"
    assert m5.model_id == "MODEL_5"
    assert m6.model_id == "MODEL_6"
    assert m10.model_id == "MODEL_10"
    assert "Institutional Sniper" in m10.name

    # Verify independent statistics
    m1.stats.record_trade(won=True, achieved_r=2.5, score=85, confirmations=5)
    assert m1.stats.trades_count == 1
    assert m1.stats.win_rate == 100.0
    assert m2.stats.trades_count == 0
    assert m10.stats.trades_count == 0


def test_state_machine_bar_expiration():
    """Validates that setup sequences expire if bars exceed sequence expiration thresholds."""
    seq = SetupSequence(
        sequence_id="SEQ_TEST_001",
        symbol="ETHUSD",
        model_id="MODEL_1",
        direction="LONG",
        current_state="SWEEP_DETECTED",
        sweep_bar_idx=10,
        max_bars_sweep_to_bos=5
    )

    # Bar index 14 (elapsed 4) -> NOT expired
    expired = seq.check_expiration(current_bar_idx=14)
    assert expired is False
    assert seq.current_state == "SWEEP_DETECTED"

    # Bar index 16 (elapsed 6 > 5) -> EXPIRED
    expired = seq.check_expiration(current_bar_idx=16)
    assert expired is True
    assert seq.current_state == "EXPIRED"
    assert seq.is_active is False


def test_model_5_evaluation():
    """Validates Model 5 breakout retest evaluation without variable errors."""
    m5 = Model5BreakoutRetest()

    # Create 30 candles with tight range 100-101, then breakout at 103, retest at 101
    candles = [make_candle(100 * i, 100.0, 101.0, 99.8, 100.5, volume=1000.0) for i in range(20)]
    # Breakout bar
    candles.append(make_candle(2100, 100.5, 104.0, 100.2, 103.5, volume=2500.0))
    # Retest bars
    candles.append(make_candle(2200, 103.5, 103.6, 101.0, 101.2, volume=1200.0))
    candles.append(make_candle(2300, 101.2, 102.5, 100.8, 102.0, volume=1500.0))
    candles.append(make_candle(2400, 102.0, 103.0, 101.5, 102.8, volume=1800.0))
    candles.append(make_candle(2500, 102.8, 103.5, 102.5, 103.2, volume=1900.0))

    ms = MarketState(
        symbol="BTCUSD",
        current_price=103.2,
        candles_5m=candles,
        candles_15m=candles
    )

    cand = m5.evaluate(ms)
    # The evaluation finishes cleanly without throwing any NameError or syntax exception
    assert cand is None or cand.model_id == "MODEL_5"

