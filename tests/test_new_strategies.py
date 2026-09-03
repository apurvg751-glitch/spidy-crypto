import pytest
from market_data.models import MarketState
from strategy.models.model_8_ob_fvg_pullback import Model8ObFvgPullback
from strategy.models.model_9_liquidity_sweep_reversal import Model9LiquiditySweepReversal


def test_model_8_and_9_initialization():
    """Validates that Model 8 (OB + FVG Pullback) and Model 9 (Liquidity Sweep Reversal ⭐) initialize with proper contracts."""
    m8 = Model8ObFvgPullback()
    m9 = Model9LiquiditySweepReversal()

    assert m8.model_id == "MODEL_8"
    assert "Order Block + FVG" in m8.name
    assert "Pullback" in m8.name

    assert m9.model_id == "MODEL_9"
    assert "Liquidity Sweep Reversal" in m9.name

    # Check empty market state rejection
    empty_market = MarketState(symbol="ETHUSD", is_stale=True)
    assert m8.evaluate(empty_market) is None
    assert m9.evaluate(empty_market) is None
