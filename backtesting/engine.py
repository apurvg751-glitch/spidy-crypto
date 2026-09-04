import logging
from typing import Optional
from market_data.models import Candle, MarketState
from strategy.setup_detector import SetupDetector
from strategy.candidate_ranking import CandidateRankingEngine
from strategy.models.base_model import StrategyCandidate
from .metrics import BacktestTrade, BacktestMetrics, calculate_backtest_metrics

logger = logging.getLogger("spidy.backtest.engine")


class BacktestEngine:
    """
    Event-driven backtesting engine for SPIDY CRYPTO.
    Enforces MAX_ACTIVE_TRADES = 1 across BTCUSD, ETHUSD, and SOLUSD.
    Evaluates setups without lookahead bias and tracks precise execution metrics.
    """

    def __init__(self, symbols: Optional[list[str]] = None):
        self.symbols = symbols or ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "AVAXUSD", "XRPUSD"]

    def run(
        self,
        market_candles_5m: dict[str, list[Candle]],
        market_candles_15m: dict[str, list[Candle]],
        market_candles_1h: Optional[dict[str, list[Candle]]] = None,
        market_candles_4h: Optional[dict[str, list[Candle]]] = None,
        min_bars: int = 30
    ) -> tuple[list[BacktestTrade], BacktestMetrics]:
        trades: list[BacktestTrade] = []
        active_trade: Optional[dict] = None

        # Determine shared timestamp progression across markets
        all_times = set()
        for sym, c_list in market_candles_5m.items():
            for c in c_list:
                all_times.add(c.time)

        sorted_times = sorted(list(all_times))
        if len(sorted_times) < min_bars + 5:
            return trades, calculate_backtest_metrics(trades)

        # Step through time chronologically
        for step_idx in range(min_bars, len(sorted_times)):
            curr_time = sorted_times[step_idx]

            # 1. First, check active trade state progression on current price bars
            if active_trade:
                trade_coin = active_trade["coin"]
                c_list = market_candles_5m.get(trade_coin, [])
                matching_bars = [c for c in c_list if c.time == curr_time]

                if matching_bars:
                    bar = matching_bars[0]
                    entry = active_trade["entry"]
                    stop = active_trade["stop_loss"]
                    t1 = active_trade["target_1"]
                    t2 = active_trade["target_2"]
                    direction = active_trade["direction"]
                    risk = abs(entry - stop)

                    # Update MFE / MAE
                    if direction == "LONG":
                        fav = (bar.high - entry) / max(risk, 1e-4)
                        adv = (entry - bar.low) / max(risk, 1e-4)
                        active_trade["mfe"] = max(active_trade["mfe"], fav)
                        active_trade["mae"] = max(active_trade["mae"], adv)

                        # Dual-touch / Stop Loss check takes priority (pessimistic / realistic execution)
                        if bar.low <= stop:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=stop,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=-1.0,
                                pnl=-risk,
                                won=False,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="STOPPED"
                            ))
                            active_trade = None

                        # Breakeven Stop (if favorable price exceeded 0.8R)
                        elif active_trade["mfe"] >= 0.8 and bar.low <= entry:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=entry,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=0.0,
                                pnl=0.0,
                                won=False,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="BREAKEVEN"
                            ))
                            active_trade = None

                        # Full Target 2 Hit
                        elif bar.high >= t2:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=t2,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=active_trade["rr"],
                                pnl=risk * active_trade["rr"],
                                won=True,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="TARGET_2"
                            ))
                            active_trade = None

                        # Target 1 Hit
                        elif bar.high >= t1:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=t1,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=1.5,
                                pnl=risk * 1.5,
                                won=True,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="TARGET_1"
                            ))
                            active_trade = None

                    elif direction == "SHORT":
                        fav = (entry - bar.low) / max(risk, 1e-4)
                        adv = (bar.high - entry) / max(risk, 1e-4)
                        active_trade["mfe"] = max(active_trade["mfe"], fav)
                        active_trade["mae"] = max(active_trade["mae"], adv)

                        # Dual-touch / Stop Loss check takes priority (pessimistic / realistic execution)
                        if bar.high >= stop:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=stop,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=-1.0,
                                pnl=-risk,
                                won=False,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="STOPPED"
                            ))
                            active_trade = None

                        # Breakeven Stop
                        elif active_trade["mfe"] >= 0.8 and bar.high >= entry:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=entry,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=0.0,
                                pnl=0.0,
                                won=False,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="BREAKEVEN"
                            ))
                            active_trade = None

                        # Full Target 2 Hit
                        elif bar.low <= t2:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=t2,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=active_trade["rr"],
                                pnl=risk * active_trade["rr"],
                                won=True,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="TARGET_2"
                            ))
                            active_trade = None

                        # Target 1 Hit
                        elif bar.low <= t1:
                            trades.append(BacktestTrade(
                                id=active_trade["id"],
                                coin=trade_coin,
                                model_id=active_trade["model_id"],
                                direction=direction,
                                entry_time=active_trade["entry_time"],
                                exit_time=curr_time,
                                entry_price=entry,
                                exit_price=t1,
                                stop_loss=stop,
                                target_1=t1,
                                target_2=t2,
                                expected_rr=active_trade["rr"],
                                achieved_r=1.5,
                                pnl=risk * 1.5,
                                won=True,
                                setup_score=active_trade["setup_score"],
                                confirmations_count=active_trade["confirmations_count"],
                                mfe=round(active_trade["mfe"], 2),
                                mae=round(active_trade["mae"], 2),
                                exit_reason="TARGET_1"
                            ))
                            active_trade = None

            # 2. If NO active trade, evaluate candidates across all 3 markets
            if not active_trade:
                candidates: list[StrategyCandidate] = []
                for sym in self.symbols:
                    candles_5 = [c for c in market_candles_5m.get(sym, []) if c.time <= curr_time]
                    candles_15 = [c for c in market_candles_15m.get(sym, []) if c.time <= curr_time]
                    if len(candles_5) < min_bars or len(candles_15) < 15:
                        continue

                    # Construct temporary market state up to current bar
                    ms = MarketState(
                        symbol=sym,
                        current_price=candles_5[-1].close,
                        last_update_ts=curr_time,
                        candles_5m=candles_5,
                        candles_15m=candles_15
                    )
                    cands = SetupDetector.evaluate_all_models(ms)
                    candidates.extend(cands)

                # Rank candidates and select ONLY ONE
                if candidates:
                    winner, _ = CandidateRankingEngine.rank_and_select(candidates)
                    if winner:
                        active_trade = {
                            "id": winner.id,
                            "coin": winner.coin,
                            "model_id": winner.model_id,
                            "direction": winner.direction,
                            "entry_time": curr_time,
                            "entry": winner.entry,
                            "stop_loss": winner.stop_loss,
                            "target_1": winner.target_1,
                            "target_2": winner.target_2,
                            "rr": winner.rr,
                            "setup_score": winner.setup_score,
                            "confirmations_count": winner.confirmations.passed_count if winner.confirmations else 0,
                            "mfe": 0.0,
                            "mae": 0.0
                        }

        metrics = calculate_backtest_metrics(trades)
        return trades, metrics
