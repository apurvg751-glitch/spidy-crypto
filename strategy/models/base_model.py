from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel, Field
from market_data.models import MarketState, ConfirmationsResult
from strategy.scoring import SetupScoreBreakdown
from strategy.state_machine import SetupSequence


class ModelStats(BaseModel):
    model_id: str
    name: str
    trades_count: int = 0
    wins_count: int = 0
    losses_count: int = 0
    win_rate: float = 0.0
    total_r: float = 0.0
    avg_r: float = 0.0
    expectancy: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    avg_setup_score: float = 0.0
    avg_confirmations: float = 0.0

    def record_trade(self, won: bool, achieved_r: float, score: int, confirmations: int):
        self.trades_count += 1
        if won:
            self.wins_count += 1
        else:
            self.losses_count += 1

        self.win_rate = round((self.wins_count / self.trades_count) * 100.0, 1)
        self.total_r += achieved_r
        self.avg_r = round(self.total_r / self.trades_count, 2)

        # Expectancy: (win_rate * avg_win) - (loss_rate * avg_loss)
        # Simplified: total_r / trades_count
        self.expectancy = self.avg_r

        win_r_sum = sum([achieved_r]) if won else 0.0
        loss_r_sum = abs(achieved_r) if not won else 0.0
        self.profit_factor = round(win_r_sum / max(loss_r_sum, 1e-4), 2)

        self.avg_setup_score = round(
            ((self.avg_setup_score * (self.trades_count - 1)) + score) / self.trades_count, 1
        )
        self.avg_confirmations = round(
            ((self.avg_confirmations * (self.trades_count - 1)) + confirmations) / self.trades_count, 1
        )


class StrategyCandidate(BaseModel):
    id: str
    coin: str
    model_id: str
    model_name: str
    direction: str                     # "LONG" or "SHORT"
    detection_timestamp: int
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    rr: float
    setup_score: int
    score_breakdown: SetupScoreBreakdown
    confirmations: ConfirmationsResult
    state_sequence: Optional[SetupSequence] = None
    reasons: list[str] = Field(default_factory=list)
    is_valid: bool = True
    grade: str = "A+"                  # "A+" or "B+"
    grade_badge: str = "🌟 GRADE: A+ (INSTITUTIONAL)"
    rejection_reason: Optional[str] = None
    generation_id: Optional[str] = None
    sweep_timestamp: Optional[int] = None
    bos_timestamp: Optional[int] = None
    ob_timestamp: Optional[int] = None
    fvg_timestamp: Optional[int] = None
    retest_timestamp: Optional[int] = None
    retest_bar_index: Optional[int] = None
    is_continuation_setup: bool = False
    overextension_ratio: float = 0.0


class BaseStrategyModel(ABC):
    """Abstract base class for all 6 independent SPIDY CRYPTO strategy models."""

    def __init__(self, model_id: str, name: str, description: str):
        self.model_id = model_id
        self.name = name
        self.description = description
        self.stats = ModelStats(model_id=model_id, name=name)
        # Sequence storage keyed by symbol
        self.active_sequences: dict[str, SetupSequence] = {}

    @abstractmethod
    def evaluate(self, market: MarketState) -> Optional[StrategyCandidate]:
        """Evaluates market state and returns a candidate setup if triggered."""
        pass
