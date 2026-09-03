from typing import Optional, Literal
from pydantic import BaseModel, Field
from config.settings import settings


SetupState = Literal[
    "WAITING",
    "SWEEP_DETECTED",
    "BOS_CONFIRMED",
    "CHOCH_DETECTED",
    "BREAKOUT_DETECTED",
    "PULLBACK_DETECTED",
    "RETEST_DETECTED",
    "CONFIRMATION",
    "READY",
    "SELECTED",
    "ACTIVE",
    "COMPLETED",
    "EXPIRED",
    "INVALIDATED",
    "BLOCKED",
    "CANCELLED",
    "STOPPED"
]


class SetupSequence(BaseModel):
    sequence_id: str
    symbol: str
    model_id: str
    direction: Literal["LONG", "SHORT"]
    current_state: SetupState = "WAITING"
    
    # State transition timestamps & bar indices
    start_bar_idx: int = -1
    sweep_bar_idx: int = -1
    bos_bar_idx: int = -1
    retest_bar_idx: int = -1
    confirmation_bar_idx: int = -1
    ready_bar_idx: int = -1

    # Key structural levels bound to this specific sequence
    sweep_level: Optional[float] = None
    extreme_level: Optional[float] = None
    bos_level: Optional[float] = None
    retest_level: Optional[float] = None

    # Expiry settings (bars)
    max_bars_sweep_to_bos: int = settings.BARS_SWEEP_TO_BOS
    max_bars_bos_to_retest: int = settings.BARS_BOS_TO_RETEST
    max_bars_retest_validity: int = settings.BARS_RETEST_VALIDITY
    max_bars_confirmation: int = settings.BARS_CONFIRMATION_AFTER_RETEST

    history_log: list[str] = Field(default_factory=list)

    def log_transition(self, new_state: SetupState, bar_idx: int, reason: str):
        self.current_state = new_state
        self.history_log.append(f"Bar {bar_idx}: -> {new_state} ({reason})")

    def check_expiration(self, current_bar_idx: int) -> bool:
        """
        Enforces sequence isolation and strict bar-expiry rules:
        - Sweep to BOS cannot exceed max_bars_sweep_to_bos
        - BOS to Retest cannot exceed max_bars_bos_to_retest
        - Retest validity cannot exceed max_bars_retest_validity
        """
        if self.current_state in ("READY", "SELECTED", "ACTIVE", "COMPLETED", "EXPIRED", "INVALIDATED"):
            return False

        if self.current_state == "SWEEP_DETECTED":
            if (current_bar_idx - self.sweep_bar_idx) > self.max_bars_sweep_to_bos:
                self.log_transition("EXPIRED", current_bar_idx, f"Sweep expired (elapsed {current_bar_idx - self.sweep_bar_idx} > {self.max_bars_sweep_to_bos} bars)")
                return True

        elif self.current_state == "BOS_CONFIRMED":
            if (current_bar_idx - self.bos_bar_idx) > self.max_bars_bos_to_retest:
                self.log_transition("EXPIRED", current_bar_idx, f"BOS to Retest expired (elapsed {current_bar_idx - self.bos_bar_idx} > {self.max_bars_bos_to_retest} bars)")
                return True

        elif self.current_state == "RETEST_DETECTED":
            if (current_bar_idx - self.retest_bar_idx) > self.max_bars_retest_validity:
                self.log_transition("EXPIRED", current_bar_idx, f"Retest validity expired (elapsed {current_bar_idx - self.retest_bar_idx} > {self.max_bars_retest_validity} bars)")
                return True

        return False

    @property
    def is_active(self) -> bool:
        return self.current_state not in ("EXPIRED", "INVALIDATED", "COMPLETED", "CANCELLED", "STOPPED")
