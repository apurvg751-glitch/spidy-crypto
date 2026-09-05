from typing import Optional, Union, Dict, Any
from pydantic import BaseModel
from config.settings import settings


class DeltaContractSpec(BaseModel):
    symbol: str
    contract_value: float  # Multiplier per contract lot (e.g. 0.001 BTC)
    contract_unit: str    # e.g. "BTC", "ETH"
    tick_size: float       # Minimum price move (e.g. 0.5 for BTC)
    point_unit: float      # Standard 1-point benchmark (e.g. 1.00 USD, 0.01 for XRP)
    point_label: str       # Human-readable point benchmark (e.g. "$1.00", "$0.01")


DELTA_CONTRACT_SPECS: Dict[str, DeltaContractSpec] = {
    "BTCUSD": DeltaContractSpec(
        symbol="BTCUSD",
        contract_value=0.001,
        contract_unit="BTC",
        tick_size=0.5,
        point_unit=1.0,
        point_label="$1.00"
    ),
    "ETHUSD": DeltaContractSpec(
        symbol="ETHUSD",
        contract_value=0.01,
        contract_unit="ETH",
        tick_size=0.05,
        point_unit=1.0,
        point_label="$1.00"
    ),
    "SOLUSD": DeltaContractSpec(
        symbol="SOLUSD",
        contract_value=1.0,
        contract_unit="SOL",
        tick_size=0.01,
        point_unit=1.0,
        point_label="$1.00"
    ),
    "BNBUSD": DeltaContractSpec(
        symbol="BNBUSD",
        contract_value=0.1,
        contract_unit="BNB",
        tick_size=0.001,
        point_unit=1.0,
        point_label="$1.00"
    ),
    "XRPUSD": DeltaContractSpec(
        symbol="XRPUSD",
        contract_value=1.0,
        contract_unit="XRP",
        tick_size=0.0001,
        point_unit=0.01,
        point_label="$0.01 (1¢)"
    ),
    "AVAXUSD": DeltaContractSpec(
        symbol="AVAXUSD",
        contract_value=1.0,
        contract_unit="AVAX",
        tick_size=0.001,
        point_unit=0.10,
        point_label="$0.10"
    ),
}


class PointValueTelemetry(BaseModel):
    symbol: str
    price: float
    margin_used: float
    leverage: int
    notional_inr: float
    notional_usd: float
    position_units: float
    contract_value: float
    contract_unit: str
    delta_contracts: float  # Number of Delta lots
    point_unit: float
    point_label: str
    point_value_usd: float  # $ gain/loss per point
    point_value_inr: float  # ₹ gain/loss per point
    tick_size: float
    tick_value_inr: float   # ₹ gain/loss per single tick move


class DeltaPointValueEngine:
    """
    Precision Point Value and Delta Contract Lot Calculator.
    Enforces exact Delta Exchange India contract specifications and PnL mechanics.
    """

    @staticmethod
    def get_spec(symbol: str) -> DeltaContractSpec:
        sym = symbol.upper()
        if sym in DELTA_CONTRACT_SPECS:
            return DELTA_CONTRACT_SPECS[sym]
        return DeltaContractSpec(
            symbol=sym,
            contract_value=1.0,
            contract_unit="UNITS",
            tick_size=0.01,
            point_unit=1.0,
            point_label="$1.00"
        )

    @classmethod
    def calculate_point_value(
        cls,
        symbol: str,
        price: float,
        margin_used: Optional[float] = None,
        leverage: Optional[int] = None,
        usd_inr_rate: Optional[float] = None
    ) -> PointValueTelemetry:
        spec = cls.get_spec(symbol)
        margin = float(margin_used or settings.MAX_ALLOWED_MARGIN)
        lev = int(leverage or settings.DEFAULT_LEVERAGE)
        rate = float(usd_inr_rate or getattr(settings, "USD_INR_RATE", 87.5))

        notional_inr = margin * lev
        notional_usd = notional_inr / max(rate, 1e-4)
        safe_price = max(price, 1e-4)
        units = notional_usd / safe_price

        # Exact Delta Exchange Contracts / Lots
        contracts = units / max(spec.contract_value, 1e-6)

        # Gain/Loss for 1 benchmark point (e.g. $1.00 or $0.01)
        point_val_usd = units * spec.point_unit
        point_val_inr = point_val_usd * rate

        # Gain/Loss for 1 minimum tick size
        tick_val_usd = units * spec.tick_size
        tick_val_inr = tick_val_usd * rate

        return PointValueTelemetry(
            symbol=symbol.upper(),
            price=round(price, 4),
            margin_used=round(margin, 2),
            leverage=lev,
            notional_inr=round(notional_inr, 2),
            notional_usd=round(notional_usd, 2),
            position_units=round(units, 6),
            contract_value=spec.contract_value,
            contract_unit=spec.contract_unit,
            delta_contracts=round(contracts, 2),
            point_unit=spec.point_unit,
            point_label=spec.point_label,
            point_value_usd=round(point_val_usd, 4),
            point_value_inr=round(point_val_inr, 2),
            tick_size=spec.tick_size,
            tick_value_inr=round(tick_val_inr, 2)
        )

    @classmethod
    def calculate_exact_pnl(
        cls,
        symbol: str,
        direction: str,
        entry: float,
        current_price: float,
        margin_used: Optional[float] = None,
        leverage: Optional[int] = None,
        usd_inr_rate: Optional[float] = None
    ) -> dict[str, Any]:
        """
        Calculates exact points moved and profit/loss strictly using Delta Exchange pricing.
        """
        pv = cls.calculate_point_value(symbol, entry, margin_used, leverage, usd_inr_rate)
        is_long = direction.upper() == "LONG"
        price_diff = (current_price - entry) if is_long else (entry - current_price)

        points_moved = price_diff / max(pv.point_unit, 1e-6)
        pnl_usd = price_diff * pv.position_units
        pnl_inr = pnl_usd * float(usd_inr_rate or getattr(settings, "USD_INR_RATE", 87.5))
        pnl_pct = (price_diff / entry) * 100.0 if entry > 0 else 0.0

        return {
            "symbol": symbol.upper(),
            "direction": direction.upper(),
            "entry": entry,
            "current_price": current_price,
            "price_diff": round(price_diff, 4),
            "points_moved": round(points_moved, 2),
            "point_unit": pv.point_unit,
            "point_label": pv.point_label,
            "point_val_inr": pv.point_value_inr,
            "point_val_usd": pv.point_value_usd,
            "delta_contracts": pv.delta_contracts,
            "contract_unit": pv.contract_unit,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_inr": round(pnl_inr, 2),
            "pnl_pct": round(pnl_pct, 2)
        }
