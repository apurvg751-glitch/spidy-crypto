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
        cooldown_seconds: Optional[int] = None,
        max_daily_loss: Optional[float] = None,
        max_consecutive_losses: Optional[int] = None,
        target_rr: Optional[float] = None,
        grade: Optional[str] = None,
        coin: Optional[str] = None,
        min_allowed_margin: Optional[float] = None,
        min_remaining_quota: Optional[float] = None,
        max_single_trade_loss: Optional[float] = None
    ) -> PositionSizeResult:
        equity = account_equity or settings.ACCOUNT_EQUITY
        risk_pct = max_risk_pct or settings.MAX_RISK_PCT
        margin_cap = max_allowed_margin or settings.MAX_ALLOWED_MARGIN
        min_margin = min_allowed_margin if min_allowed_margin is not None else getattr(settings, "MIN_ALLOWED_MARGIN", 3000.0)
        max_margin = margin_cap if margin_cap is not None else getattr(settings, "MAX_ALLOWED_MARGIN", 4500.0)
        lev = leverage or settings.DEFAULT_LEVERAGE
        cooldown = cooldown_seconds if cooldown_seconds is not None else settings.COOLDOWN_SECONDS
        now = int(time.time())

        # 1. Minimum Equity Guard (All trades allowed within ₹3,000 to ₹4,500 band)
        if equity < min_margin:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Account equity (₹{equity:,.2f}) is below minimum allowed margin threshold of ₹{min_margin:,.2f}"
            )

        # 2. Daily Loss Guard & Quota Clamping (Halt if remaining quota <= 20 threshold)
        daily_limit = max_daily_loss if max_daily_loss is not None else (settings.MAX_DAILY_LOSS if getattr(settings, "ENABLE_DAILY_LOSS_LIMIT", False) else None)
        if daily_limit is not None and current_daily_loss >= daily_limit:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Max daily loss reached ({current_daily_loss:.2f} >= {daily_limit:.2f})"
            )

        quota_floor = min_remaining_quota if min_remaining_quota is not None else getattr(settings, "MIN_REMAINING_DAILY_LOSS_QUOTA", 20.0)
        remaining_quota = max(0.0, daily_limit - current_daily_loss) if daily_limit is not None else None
        if remaining_quota is not None and remaining_quota <= quota_floor:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Insufficient remaining daily loss quota (₹{remaining_quota:.2f} <= ₹{quota_floor:.2f} threshold). Trading halted to protect capital."
            )

        # 3. Consecutive Losses Guard (Disabled per user configuration)
        consec_limit = max_consecutive_losses if max_consecutive_losses is not None else (settings.MAX_CONSECUTIVE_LOSSES if getattr(settings, "ENABLE_CONSECUTIVE_LOSS_LIMIT", False) else None)
        if consec_limit is not None and consecutive_losses >= consec_limit:
            return PositionSizeResult(
                is_allowed=False,
                rejection_reason=f"Max consecutive losses reached ({consecutive_losses} >= {consec_limit})"
            )

        # 4. Cooldown Guard
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

        # Dynamic Live Margin Band (₹3,000 – ₹4,500)
        # If equity is below the margin ceiling, scale down to 95% of available equity as a buffer
        if equity < max_margin:
            usable_equity = equity * 0.95
        else:
            usable_equity = max_margin

        base_margin = max(min_margin * 0.90, min(usable_equity, max_margin))
        if margin_cap is not None:
            base_margin = min(base_margin, margin_cap)

        # Dynamic Variable Margin Adjustment:
        # If a setup has a slightly lower swing high (1.6R <= RR < 2.0R),
        # dynamically scale margin (e.g. 70% to 90%) to reduce risk exposure on tighter clearance.
        margin_multiplier = 1.0
        if target_rr is not None and target_rr < 2.0:
            # Scale proportionally: 1.8R gives (1.8/2.0) = 0.90x, clamped to min 0.70x (70% margin)
            margin_multiplier = max(0.70, min(1.0, target_rr / 2.0))
        elif grade and grade.upper() == "B+":
            margin_multiplier = 0.75

        required_margin = round(base_margin * margin_multiplier, 2)
        notional = required_margin * lev
        usd_rate = getattr(settings, "USD_INR_RATE", 87.5)
        notional_usd = notional / usd_rate
        units = notional_usd / entry
        risk_amount = (units * stop_dist) * usd_rate

        # Max Single Trade Loss & Dynamic Quota Clamping:
        # Strictly caps per-trade risk at ₹125.00 (or remaining daily quota, whichever is tighter).
        trade_risk_cap = max_single_trade_loss if max_single_trade_loss is not None else getattr(settings, "MAX_TRADE_LOSS", 125.0)
        if remaining_quota is not None and current_daily_loss > 0:
            effective_risk_cap = min(trade_risk_cap, remaining_quota)
        else:
            effective_risk_cap = trade_risk_cap

        if risk_amount > effective_risk_cap:
            max_units_by_cap = (effective_risk_cap / usd_rate) / stop_dist

            # Minimum contract units guard based on asset specifications
            min_units = 0.001
            if coin:
                sym_clean = coin.upper()
                if "BTC" in sym_clean:
                    min_units = 0.001
                elif "ETH" in sym_clean:
                    min_units = 0.01
                elif "SOL" in sym_clean:
                    min_units = 0.1
                elif "XRP" in sym_clean:
                    min_units = 1.0
                elif "AVAX" in sym_clean:
                    min_units = 0.5

            if max_units_by_cap < min_units:
                min_risk = (min_units * stop_dist) * usd_rate
                return PositionSizeResult(
                    is_allowed=False,
                    rejection_reason=f"Structural stop distance ({stop_dist:.4f}) requires ₹{min_risk:.2f} minimum risk, exceeding allowed trade risk cap of ₹{effective_risk_cap:.2f}"
                )

            units = max_units_by_cap
            notional_usd = units * entry
            notional = notional_usd * usd_rate
            required_margin = round(notional / lev, 2)
            risk_amount = round((units * stop_dist) * usd_rate, 2)

        risk_pct = round((risk_amount / max(required_margin, 1.0)) * 100.0, 2)

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

