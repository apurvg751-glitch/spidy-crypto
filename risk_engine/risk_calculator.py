from typing import Optional
from pydantic import BaseModel


class TradeLevels(BaseModel):
    entry: float
    stop_loss: float
    target_1: float
    target_2: float
    risk: float
    reward: float
    risk_reward: float
    is_valid: bool
    rejection_reason: Optional[str] = None


class RiskEngine:
    """Calculates risk parameters, invalidation stops, profit targets, and RR ratios."""

    @staticmethod
    def calculate_levels(
        direction: str,
        current_price: float,
        extreme_level: float,
        atr: float,
        min_rr: float = 1.5,
        grade: str = "A+"
    ) -> TradeLevels:
        """
        Calculates entry, stop, Target 1, Target 2, and RR.
        - Grade A+: Standard buffer (0.35 * ATR), T1 (1.8R), T2 (2.5R).
        - Grade B+: Stricter tight SL (0.15 * ATR), Quick T1 (1.4R), Cautious T2 (1.8R).
        """
        entry = current_price
        
        # Adaptive buffer based on institutional setup grade
        if grade.upper() == "B+":
            buffer = max(atr * 0.15, entry * 0.0002)  # Stricter tight SL
            t1_mult = 1.6                             # Quick TP (Min 1.6R)
            t2_mult = 1.8                             # Cautious T2
        else:
            buffer = max(atr * 0.35, entry * 0.0005)  # Institutional standard buffer
            t1_mult = 1.8                             # Standard T1
            t2_mult = 2.5                             # Full T2

        if direction == "LONG":
            stop = extreme_level - buffer
            if stop >= entry:
                stop = entry - (atr * (0.6 if grade == "B+" else 1.0))

            risk = entry - stop
            if risk <= 0:
                return TradeLevels(
                    entry=entry, stop_loss=stop, target_1=entry, target_2=entry,
                    risk=0, reward=0, risk_reward=0, is_valid=False,
                    rejection_reason="Invalid risk distance (stop >= entry)"
                )

            t1 = entry + (risk * t1_mult)
            t2 = entry + (risk * t2_mult)
            reward = t2 - entry
            rr = reward / risk

        elif direction == "SHORT":
            stop = extreme_level + buffer
            if stop <= entry:
                stop = entry + (atr * (0.6 if grade == "B+" else 1.0))

            risk = stop - entry
            if risk <= 0:
                return TradeLevels(
                    entry=entry, stop_loss=stop, target_1=entry, target_2=entry,
                    risk=0, reward=0, risk_reward=0, is_valid=False,
                    rejection_reason="Invalid risk distance (stop <= entry)"
                )

            t1 = entry - (risk * t1_mult)
            t2 = entry - (risk * t2_mult)
            reward = entry - t2
            rr = reward / risk

        else:
            return TradeLevels(
                entry=entry, stop_loss=0, target_1=0, target_2=0,
                risk=0, reward=0, risk_reward=0, is_valid=False,
                rejection_reason=f"Unknown direction: {direction}"
            )

        # Validation: Stop loss cannot be zero or negative
        if stop <= 0 or entry <= 0:
            return TradeLevels(
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                risk=risk, reward=reward, risk_reward=rr, is_valid=False,
                rejection_reason="Calculated price or stop loss is <= 0"
            )

        if rr < min_rr:
            return TradeLevels(
                entry=entry, stop_loss=stop, target_1=t1, target_2=t2,
                risk=risk, reward=reward, risk_reward=round(rr, 2), is_valid=False,
                rejection_reason=f"Reward to Risk ({rr:.2f}) below minimum {min_rr}"
            )

        return TradeLevels(
            entry=round(entry, 4),
            stop_loss=round(stop, 4),
            target_1=round(t1, 4),
            target_2=round(t2, 4),
            risk=round(risk, 4),
            reward=round(reward, 4),
            risk_reward=round(rr, 2),
            is_valid=True
        )
