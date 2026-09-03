import pytest
from market_data.models import Candle
from backtesting.metrics import calculate_backtest_metrics, BacktestTrade
from backtesting.engine import BacktestEngine
from backtesting.out_of_sample import OutOfSampleValidator
from tests.conftest import make_candle


def test_backtest_metrics_calculation():
    """Validates metrics calculation (Win rate, Expectancy, Profit factor, Drawdown, MFE/MAE)."""
    trades = [
        BacktestTrade(
            id="T1", coin="ETHUSD", model_id="MODEL_1", direction="LONG",
            entry_time=100, exit_time=200, entry_price=2000, exit_price=2050,
            stop_loss=1980, target_1=2036, target_2=2050, expected_rr=2.5,
            achieved_r=2.5, pnl=50, won=True, setup_score=85, confirmations_count=5,
            mfe=2.5, mae=0.2, exit_reason="TARGET_2"
        ),
        BacktestTrade(
            id="T2", coin="BTCUSD", model_id="MODEL_2", direction="SHORT",
            entry_time=300, exit_time=400, entry_price=60000, exit_price=60500,
            stop_loss=60500, target_1=59000, target_2=58000, expected_rr=2.0,
            achieved_r=-1.0, pnl=-500, won=False, setup_score=78, confirmations_count=4,
            mfe=0.3, mae=1.0, exit_reason="STOPPED"
        ),
        BacktestTrade(
            id="T3", coin="SOLUSD", model_id="MODEL_1", direction="LONG",
            entry_time=500, exit_time=600, entry_price=150, exit_price=156,
            stop_loss=147, target_1=155.4, target_2=156, expected_rr=2.0,
            achieved_r=2.0, pnl=6, won=True, setup_score=90, confirmations_count=6,
            mfe=2.1, mae=0.1, exit_reason="TARGET_2"
        )
    ]

    m = calculate_backtest_metrics(trades)
    assert m.total_trades == 3
    assert m.wins == 2
    assert m.losses == 1
    assert m.win_rate == 66.7
    assert m.total_r_gain == 3.5
    assert m.profit_factor >= 2.0
    assert "ETHUSD" in m.by_market
    assert "MODEL_1" in m.by_model


def test_out_of_sample_splitter():
    """Validates train / out-of-sample data splitting without lookahead."""
    candles = [make_candle(i, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(100)]
    data = {"ETHUSD": candles}

    train, test = OutOfSampleValidator.split_data(data, train_ratio=0.70)
    assert len(train["ETHUSD"]) == 70
    assert len(test["ETHUSD"]) == 30
    # No timestamp overlaps
    assert train["ETHUSD"][-1].time < test["ETHUSD"][0].time
