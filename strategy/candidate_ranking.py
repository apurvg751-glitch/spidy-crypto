from typing import Optional
from strategy.models.base_model import StrategyCandidate


class CandidateRankingEngine:
    """
    Arbitrates and ranks trading candidates across ETHUSD, BTCUSD, and SOLUSD and all 6 models.
    Deterministic selection rule:
    1. Highest Setup Score
    2. Most Confirmations passed (X/7)
    3. Highest Expected Risk-to-Reward (RR)
    4. Model Priority (Model 1 > Model 4 > Model 3 > Model 2 > Model 5 > Model 6)
    5. Earliest / freshest detection timestamp
    """

    MODEL_PRIORITY_WEIGHT = {
        "MODEL_1": 6,   # Liquidity Sweep Reversal (Highest Priority Core)
        "MODEL_4": 5,   # CHoCH Reversal
        "MODEL_3": 4,   # Order Block + FVG
        "MODEL_2": 3,   # BOS Continuation
        "MODEL_5": 2,   # Breakout Retest
        "MODEL_6": 1    # Trend Pullback
    }

    @classmethod
    def rank_and_select(cls, candidates: list[StrategyCandidate]) -> tuple[Optional[StrategyCandidate], list[tuple[StrategyCandidate, str]]]:
        if not candidates:
            return None, []

        valid = [c for c in candidates if c.is_valid and c.setup_score >= 70]
        if not valid:
            return None, []

        def sort_key(cand: StrategyCandidate):
            score = cand.setup_score
            confs = cand.confirmations.passed_count if cand.confirmations else 0
            rr = cand.rr
            model_wt = cls.MODEL_PRIORITY_WEIGHT.get(cand.model_id, 0)
            recency = cand.detection_timestamp
            return (score, confs, rr, model_wt, recency)

        ranked = sorted(valid, key=sort_key, reverse=True)
        winner = ranked[0]
        losers = ranked[1:]

        rejected_with_reasons: list[tuple[StrategyCandidate, str]] = []
        for loser in losers:
            reason = (
                f"Selected {winner.coin} [{winner.model_name}] (Score: {winner.setup_score}, "
                f"Confirmations: {winner.confirmations.passed_count}/7, RR: 1:{winner.rr:.1f}) over "
                f"{loser.coin} [{loser.model_name}] (Score: {loser.setup_score}, "
                f"Confirmations: {loser.confirmations.passed_count}/7, RR: 1:{loser.rr:.1f})"
            )
            rejected_with_reasons.append((loser, reason))

        return winner, rejected_with_reasons
