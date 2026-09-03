import pytest
from market_data.models import Candle, MultiTimeframeContext, OrderBlock, FairValueGap
from strategy.confirmation_engine import ConfirmationEngine
from tests.conftest import make_candle


def test_seven_confirmations_evaluation():
    """Validates 7 confirmations framework, score rating, and >= 4/7 gate."""
    # Synthetic bullish candles
    c5 = [
        make_candle(1, 100, 102, 99, 101, volume=500),
        make_candle(2, 101, 103, 100, 102, volume=600),
        make_candle(3, 102, 104, 101, 103, volume=700),
        make_candle(4, 103, 105, 102, 104, volume=800),
        make_candle(5, 104, 106, 103, 105, volume=900),
        make_candle(6, 105, 107, 104, 106, volume=1000),
        make_candle(7, 106, 108, 105, 107, volume=1100),
        make_candle(8, 107, 109, 106, 108, volume=1200),
        make_candle(9, 108, 110, 107, 109, volume=1300),
        # Final confirmation candle: strong volume & bullish pinbar/rejection
        make_candle(10, 108.5, 112, 107, 111.5, volume=2500)
    ]
    c15 = c5

    mtf = MultiTimeframeContext(
        symbol="ETHUSD",
        macro_bias_4h="Bullish",
        trend_1h="Bullish",
        exec_context_15m="Bullish",
        struct_5m="Bullish",
        ema200_bias="Bullish"
    )

    ob = OrderBlock(
        id="OB_1",
        symbol="ETHUSD",
        direction="BULLISH",
        top=107.5,
        bottom=105.0,
        candle_index=5,
        creation_time=5
    )

    res = ConfirmationEngine.evaluate(
        direction="LONG",
        candles_5m=c5,
        candles_15m=c15,
        mtf_context=mtf,
        active_ob=ob,
        active_fvg=None
    )

    assert res.trend_ok is True
    assert res.ob_ok is True
    assert res.volume_ok is True
    assert res.passed_count >= 4
    assert res.is_qualified is True
    assert res.rating in ("QUALIFIED", "STRONG", "VERY_STRONG", "EXCEPTIONAL")
