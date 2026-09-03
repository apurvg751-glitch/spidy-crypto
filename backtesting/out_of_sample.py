from typing import Any
from market_data.models import Candle
from .engine import BacktestEngine
from .metrics import BacktestMetrics


class OutOfSampleValidator:
    """
    Validates strategy models against out-of-sample data:
    - Splits historical dataset into In-Sample (Train/Dev) and Out-of-Sample (Test)
    - Compares win rate, profit factor, and expectancy to ensure edge holds without overfitting.
    """

    @staticmethod
    def split_data(
        candles_by_symbol: dict[str, list[Candle]],
        train_ratio: float = 0.70
    ) -> tuple[dict[str, list[Candle]], dict[str, list[Candle]]]:
        train_dict = {}
        test_dict = {}

        for sym, candles in candles_by_symbol.items():
            if not candles:
                train_dict[sym] = []
                test_dict[sym] = []
                continue
            split_idx = int(len(candles) * train_ratio)
            train_dict[sym] = candles[:split_idx]
            test_dict[sym] = candles[split_idx:]

        return train_dict, test_dict

    @classmethod
    def run_validation(
        cls,
        candles_5m: dict[str, list[Candle]],
        candles_15m: dict[str, list[Candle]],
        train_ratio: float = 0.70
    ) -> dict[str, Any]:
        train_5m, test_5m = cls.split_data(candles_5m, train_ratio)
        train_15m, test_15m = cls.split_data(candles_15m, train_ratio)

        engine = BacktestEngine()

        train_trades, train_metrics = engine.run(train_5m, train_15m)
        test_trades, test_metrics = engine.run(test_5m, test_15m)

        # Performance retention ratio
        wr_retention = round((test_metrics.win_rate / max(train_metrics.win_rate, 1.0)) * 100.0, 1)
        pf_retention = round((test_metrics.profit_factor / max(train_metrics.profit_factor, 1.0)) * 100.0, 1)

        is_robust = (test_metrics.win_rate >= 45.0) and (test_metrics.profit_factor >= 1.0)

        return {
            "is_robust": is_robust,
            "train_ratio": train_ratio,
            "in_sample_trades": len(train_trades),
            "in_sample_metrics": train_metrics.model_dump(),
            "out_of_sample_trades": len(test_trades),
            "out_of_sample_metrics": test_metrics.model_dump(),
            "retention": {
                "win_rate_retention_pct": wr_retention,
                "profit_factor_retention_pct": pf_retention
            }
        }
