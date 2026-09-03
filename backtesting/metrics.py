from typing import Any
from pydantic import BaseModel, Field


class BacktestTrade(BaseModel):
    id: str
    coin: str
    model_id: str
    direction: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    stop_loss: float
    target_1: float
    target_2: float
    expected_rr: float
    achieved_r: float
    pnl: float
    won: bool
    setup_score: int
    confirmations_count: int
    mfe: float = 0.0          # Max Favorable Excursion (R)
    mae: float = 0.0          # Max Adverse Excursion (R)
    exit_reason: str = ""     # "TARGET_2", "TARGET_1", "STOPPED", "EXPIRED"


class BacktestMetrics(BaseModel):
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    avg_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_r: float = 0.0
    max_consecutive_losses: int = 0
    total_r_gain: float = 0.0

    # Breakdown metrics
    by_market: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_confirmation: dict[str, dict[str, Any]] = Field(default_factory=dict)
    by_score_range: dict[str, dict[str, Any]] = Field(default_factory=dict)


def calculate_backtest_metrics(trades: list[BacktestTrade]) -> BacktestMetrics:
    if not trades:
        return BacktestMetrics()

    total = len(trades)
    wins = [t for t in trades if t.won]
    losses = [t for t in trades if not t.won]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = round((win_count / total) * 100.0, 1)

    avg_win = sum(t.achieved_r for t in wins) / max(win_count, 1)
    avg_loss = abs(sum(t.achieved_r for t in losses) / max(loss_count, 1))

    total_r = sum(t.achieved_r for t in trades)
    avg_r = round(total_r / total, 2)
    win_p = win_count / total
    loss_p = loss_count / total
    expectancy = round((win_p * avg_win) - (loss_p * avg_loss), 2)

    win_sum = sum(t.achieved_r for t in wins)
    loss_sum = abs(sum(t.achieved_r for t in losses))
    profit_factor = round(win_sum / max(loss_sum, 1e-4), 2)

    # Calculate equity curve & max drawdown
    cum_r = 0.0
    peak_r = 0.0
    max_dd = 0.0
    cur_consec_losses = 0
    max_consec_losses = 0

    for t in trades:
        cum_r += t.achieved_r
        if cum_r > peak_r:
            peak_r = cum_r
        dd = peak_r - cum_r
        if dd > max_dd:
            max_dd = dd

        if not t.won:
            cur_consec_losses += 1
            if cur_consec_losses > max_consec_losses:
                max_consec_losses = cur_consec_losses
        else:
            cur_consec_losses = 0

    # Breakdown by market
    by_market = {}
    for coin in ("ETHUSD", "BTCUSD", "SOLUSD"):
        m_trades = [t for t in trades if t.coin == coin]
        if m_trades:
            m_wins = len([t for t in m_trades if t.won])
            by_market[coin] = {
                "trades": len(m_trades),
                "win_rate": round((m_wins / len(m_trades)) * 100.0, 1),
                "total_r": round(sum(t.achieved_r for t in m_trades), 2)
            }

    # Breakdown by model
    by_model = {}
    for t in trades:
        m_id = t.model_id
        if m_id not in by_model:
            by_model[m_id] = {"trades": 0, "wins": 0, "total_r": 0.0}
        by_model[m_id]["trades"] += 1
        if t.won:
            by_model[m_id]["wins"] += 1
        by_model[m_id]["total_r"] = round(by_model[m_id]["total_r"] + t.achieved_r, 2)

    for m_id, dat in by_model.items():
        dat["win_rate"] = round((dat["wins"] / dat["trades"]) * 100.0, 1)

    # Breakdown by confirmation count
    by_conf = {}
    for c_num in (4, 5, 6, 7):
        c_trades = [t for t in trades if t.confirmations_count == c_num]
        if c_trades:
            c_wins = len([t for t in c_trades if t.won])
            by_conf[f"{c_num}/7"] = {
                "trades": len(c_trades),
                "win_rate": round((c_wins / len(c_trades)) * 100.0, 1),
                "avg_r": round(sum(t.achieved_r for t in c_trades) / len(c_trades), 2)
            }

    # Breakdown by score range
    by_score = {}
    for label, r_min, r_max in [("70-79", 70, 79), ("80-89", 80, 89), ("90-100", 90, 100)]:
        s_trades = [t for t in trades if r_min <= t.setup_score <= r_max]
        if s_trades:
            s_wins = len([t for t in s_trades if t.won])
            by_score[label] = {
                "trades": len(s_trades),
                "win_rate": round((s_wins / len(s_trades)) * 100.0, 1),
                "total_r": round(sum(t.achieved_r for t in s_trades), 2)
            }

    return BacktestMetrics(
        total_trades=total,
        wins=win_count,
        losses=loss_count,
        win_rate=win_rate,
        avg_win_r=round(avg_win, 2),
        avg_loss_r=round(avg_loss, 2),
        avg_r=avg_r,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_drawdown_r=round(max_dd, 2),
        max_consecutive_losses=max_consec_losses,
        total_r_gain=round(total_r, 2),
        by_market=by_market,
        by_model=by_model,
        by_confirmation=by_conf,
        by_score_range=by_score
    )
