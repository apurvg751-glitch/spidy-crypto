import pytest
from market_data.models import Candle, MarketState, MultiTimeframeContext
from strategy.models import (
    Model11AsianJudasSwing,
    Model12InversionFvg,
    Model13BreakerBlock,
    Model14SmtDivergence
)
from strategy.setup_detector import SetupDetector


def test_instantiate_4_new_models():
    m11 = Model11AsianJudasSwing()
    m12 = Model12InversionFvg()
    m13 = Model13BreakerBlock()
    m14 = Model14SmtDivergence()

    assert m11.model_id == "MODEL_11"
    assert m12.model_id == "MODEL_12"
    assert m13.model_id == "MODEL_13"
    assert m14.model_id == "MODEL_14"


def test_models_integrated_in_setup_detector():
    ms = MarketState(
        symbol="ETHUSD",
        current_price=2500.0,
        candles_5m=[],
        candles_15m=[]
    )
    # With empty candles, evaluate_all_models returns [] safely without crashing
    cands = SetupDetector.evaluate_all_models(ms)
    assert isinstance(cands, list)
