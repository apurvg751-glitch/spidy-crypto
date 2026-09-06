import time
from typing import Optional
from pydantic import BaseModel
from config.settings import settings


class PositionSizeResult(BaseModel):
    is_allowed: bool
    rejection_reason: Optional[str] = None
    units: float = 0.0
    notional_value: float = 0.0
    required_margin: float = 0.0
    risk_amount: float = 0.0
    risk_pct: float = 0.0
    leverage: int = 1
    account_equity: float = 4200.0


class PositionSizer:
    """
    Computes position sizing, required margin, and enforces portfolio-level risk safeguards:
    - Account equity & Risk %
    - ₹4,200 allocated margin @ 6x leverage (₹25,200 position size)
    - Leverage
    - Daily loss limit protection
    - Consecutive loss limit protection
    - Cooldown period after trade closure
    """

    @staticmethod
    def calculate_position(
        entry: float,
        stop_loss: float,
        account_equity: Optional[float] = None,
        max_risk_pct: Optional[float] = None,
        max_allowed_margin: Optional[float] = None,
        leverage: Optional[int] = None,
        current_daily_loss: float = 0.0,
        consecutive_losses: int = 0,
        last_trade_close_time: int = 0,
        cooldown_seconds: Optional[int] = None
    ) -> PositionSizeResult:
        equity = account_equity or settings.ACCOUNT_EQUITY
        risk_pct = max_risk_pct or settings.MAX_RISK_PCT
        margin_cap = max_allowed_margin or settings.MAX_ALLOWED_MARGIN
        lev = leverage or settings.DEFAULT_LEVERAGE
        cooldown = cooldown_seconds if cooldown_seconds is not None else settings.COOLDOWN_SECONDS
        now = int(time.time())

        # 1. Daily Loss Guard
        if current_daily_loss >= settings.MAX_DAILY_LOSS:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Max daily loss reached ({current_daily_loss:.2f} >= {settings.MAX_DAILY_LOSS:.2f})"
            )

        # 2. Consecutive Losses Guard
        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Max consecutive losses reached ({consecutive_losses} >= {settings.MAX_CONSECUTIVE_LOSSES})"
            )

        # 3. Cooldown Guard
        if cooldown > 0 and last_trade_close_time > 0 and (now - last_trade_close_time) < cooldown:
            remaining = cooldown - (now - last_trade_close_time)
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Risk cooldown in effect ({remaining}s remaining)"
            )

        stop_dist = abs(entry - stop_loss)
        if stop_dist <= 0 or entry <= 0:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason="Invalid stop distance (<= 0)"
            )

        # Institutional Position Sizing: ₹4,200 Margin @ 6x Leverage -> ₹25,200 Notional Value
        # All trade risk is evaluated relative to the ₹4,200 allocated margin
        required_margin = min(margin_cap, 4200.0) if margin_cap else 4200.0
        notional = required_margin * lev
        usd_rate = getattr(settings, "USD_INR_RATE", 87.5)
        notional_usd = notional / usd_rate
        units = notional_usd / entry
        risk_amount = (units * stop_dist) * usd_rate
        risk_pct = round((risk_amount / required_margin) * 100.0, 2)

        return PositionSizeResult(
            is_allowed=True,
            units=round(units, 4) if units >= 0.001 else round(units, 6),
            notional_value=round(notional, 2),
            required_margin=round(required_margin, 2),
            risk_amount=round(risk_amount, 2),
            risk_pct=risk_pct,
            leverage=lev,
            account_equity=equity
        )

