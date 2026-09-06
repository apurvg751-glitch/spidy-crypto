import pytest
from config.settings import settings
from strategy.setup_detector import SetupDetector
from market_data.models import MarketState, Candle
import time

def create_mock_candles(count: int = 40, base_price: float = 100.0) -> list[Candle]:
    now = int(time.time())
    candles = []
    for i in range(count):
        t = now - (count - i) * 300
        candles.append(Candle(
            time=t,
            open=base_price + (i * 0.1),
            high=base_price + (i * 0.1) + 0.5,
            low=base_price + (i * 0.1) - 0.5,
            close=base_price + (i * 0.1) + 0.2,
            volume=1000.0,
            is_closed=True
        ))
    return candles


def test_quarantined_models_disabled_by_default():
    assert 'MODEL_8' in settings.DISABLED_MODELS
    assert 'MODEL_9' in settings.DISABLED_MODELS


def test_setup_detector_filters_disabled_models():
    c5 = create_mock_candles(50, 100.0)
    c15 = create_mock_candles(30, 100.0)
    market = MarketState(
        symbol='SOLUSD',
        candles_5m=c5,
        candles_15m=c15,
        current_price=105.0
    )
    candidates = SetupDetector.evaluate_all_models(market)
    for c in candidates:
        assert c.model_id not in settings.DISABLED_MODELS
        assert c.model_id not in ('MODEL_8', 'MODEL_9')
