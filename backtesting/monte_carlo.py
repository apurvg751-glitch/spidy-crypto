import logging
import random
from typing import Dict, Any, List

logger = logging.getLogger("spidy.monte_carlo")


class MonteCarloEngine:
    """
    Quantitative Monte Carlo Simulation & Ruin Risk Engine.
    Simulates thousands of randomized trade sequence paths to quantify
    maximum drawdown boundaries, risk of ruin, and expected return percentiles.
    """

    @staticmethod
    def run_simulation(
        initial_capital: float = 4200.0,
        win_rate: float = 0.65,
        avg_win_r: float = 1.8,
        avg_loss_r: float = 1.0,
        risk_per_trade_pct: float = 1.5,
        num_trades: int = 100,
        num_simulations: int = 500
    ) -> Dict[str, Any]:
        """
        Executes randomized trade iterations and computes statistical confidence intervals.
        """
        all_final_capitals = []
        all_max_drawdowns = []

        risk_fraction = risk_per_trade_pct / 100.0

        for _ in range(num_simulations):
            equity = initial_capital
            peak = initial_capital
            max_dd = 0.0

            for _ in range(num_trades):
                bet = equity * risk_fraction
                is_win = (random.random() < win_rate)

                if is_win:
                    equity += bet * avg_win_r
                else:
                    equity -= bet * avg_loss_r

                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak if peak > 0 else 1.0
                if dd > max_dd:
                    max_dd = dd

            all_final_capitals.append(equity)
            all_max_drawdowns.append(max_dd)

        all_final_capitals.sort()
        all_max_drawdowns.sort()

        p5_idx = int(num_simulations * 0.05)
        p50_idx = int(num_simulations * 0.50)
        p95_idx = int(num_simulations * 0.95)

        ruin_count = sum(1 for c in all_final_capitals if c < (initial_capital * 0.5))
        ruin_probability = (ruin_count / num_simulations) * 100.0

        return {
            "num_simulations": num_simulations,
            "num_trades": num_trades,
            "initial_capital": initial_capital,
            "median_equity": round(all_final_capitals[p50_idx], 2),
            "percentile_5_worst_equity": round(all_final_capitals[p5_idx], 2),
            "percentile_95_best_equity": round(all_final_capitals[p95_idx], 2),
            "median_max_drawdown_pct": round(all_max_drawdowns[p50_idx] * 100.0, 2),
            "worst_case_drawdown_pct": round(all_max_drawdowns[p95_idx] * 100.0, 2),
            "ruin_probability_pct": round(ruin_probability, 2),
            "status": "APPROVED_ROBUST" if ruin_probability < 1.0 else "HIGH_RISK"
        }
