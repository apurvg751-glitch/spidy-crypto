import math
import time
from dataclasses import dataclass
from typing import List, Optional
from market_data.models import Candle


from config.precision import round_price, format_price, get_symbol_tick_size


@dataclass
class SessionVWAPResult:
    session_name: str
    vwap: float
    vah: float          # Value Area High (+1.0 sigma)
    val: float          # Value Area Low (-1.0 sigma)
    poc: float          # Point of Control (Highest Volume Price)
    current_relation: str # "ABOVE_VAH", "INSIDE_VALUE_AREA", "BELOW_VAL"
    bias_confluence: str  # "BULLISH_DISCOUNT", "BEARISH_PREMIUM", "NEUTRAL"
    confluence_score: int # 0 to 10 bonus points
    description: str


class SessionVWAPEngine:
    """
    Institutional Session-Anchored VWAP and Value Area Engine.
    Anchors to:
    - Asia: 00:00 UTC
    - London: 08:00 UTC
    - New York: 13:30 UTC
    Computes VWAP, VAH (+1 std), VAL (-1 std), and POC (Point of Control).
    """

    @staticmethod
    def _get_active_session_start(timestamp: Optional[int] = None) -> tuple[str, int]:
        """Returns the current active session name and its anchor UTC timestamp."""
        ts = timestamp or int(time.time())
        # Convert timestamp to seconds since midnight UTC
        seconds_in_day = ts % 86400
        midnight_utc = ts - seconds_in_day

        asia_start = midnight_utc + (0 * 3600)        # 00:00 UTC
        london_start = midnight_utc + (8 * 3600)      # 08:00 UTC
        ny_start = midnight_utc + int(13.5 * 3600)    # 13:30 UTC

        if ts >= ny_start:
            return "New York Session", ny_start
        elif ts >= london_start:
            return "London Session", london_start
        else:
            return "Asia Session", asia_start

    @classmethod
    def calculate(
        cls,
        candles_5m: List[Candle],
        current_price: Optional[float] = None,
        symbol: str = "ETHUSD"
    ) -> Optional[SessionVWAPResult]:
        if not candles_5m or len(candles_5m) < 5:
            return None

        now = int(time.time())
        session_name, session_start = cls._get_active_session_start(now)

        # Filter candles for current session
        session_candles = [c for c in candles_5m if c.time >= session_start]
        # If less than 3 candles in current session, use last 24 candles as rolling anchor
        if len(session_candles) < 3:
            session_candles = candles_5m[-24:]
            session_name = f"{session_name} (Rolling 2H Anchor)"

        cum_vol = 0.0
        cum_tp_vol = 0.0
        typical_prices = []
        volumes = []

        # POC tracking (histogram with bin size ~ 0.05% of price, bounded by symbol tick size)
        curr = current_price or candles_5m[-1].close
        tick_size = get_symbol_tick_size(symbol)
        bin_size = max(tick_size, curr * 0.0005)
        volume_by_bin = {}

        for c in session_candles:
            tp = (c.high + c.low + c.close) / 3.0
            vol = max(1.0, c.volume)
            cum_vol += vol
            cum_tp_vol += (tp * vol)
            typical_prices.append(tp)
            volumes.append(vol)

            # Binning for POC
            bin_idx = round(tp / bin_size) * bin_size
            volume_by_bin[bin_idx] = volume_by_bin.get(bin_idx, 0.0) + vol

        if cum_vol <= 0:
            return None

        vwap = cum_tp_vol / cum_vol

        # Variance & Standard Deviation
        variance_sum = 0.0
        for tp, vol in zip(typical_prices, volumes):
            variance_sum += vol * ((tp - vwap) ** 2)

        std_dev = math.sqrt(variance_sum / cum_vol) if cum_vol > 0 else 0.0
        vah = vwap + std_dev
        val = vwap - std_dev

        # Point of Control
        poc = max(volume_by_bin.items(), key=lambda x: x[1])[0] if volume_by_bin else vwap

        # Relation & Confluence
        ref_price = current_price or candles_5m[-1].close
        if ref_price > vah:
            relation = "ABOVE_VAH"
            bias = "BEARISH_PREMIUM"
            confluence = 10
            desc = f"Price ({format_price(symbol, ref_price)}) ABOVE VAH ({format_price(symbol, vah)}) | Extended Premium (Reversal Bias)"
        elif ref_price < val:
            relation = "BELOW_VAL"
            bias = "BULLISH_DISCOUNT"
            confluence = 10
            desc = f"Price ({format_price(symbol, ref_price)}) BELOW VAL ({format_price(symbol, val)}) | Extended Discount (Rebound Bias)"
        else:
            relation = "INSIDE_VALUE_AREA"
            if ref_price >= vwap:
                bias = "NEUTRAL_BULLISH"
                confluence = 5
                desc = f"Price ({format_price(symbol, ref_price)}) above VWAP ({format_price(symbol, vwap)}) inside Value Area (VAH: {format_price(symbol, vah)}, POC: {format_price(symbol, poc)})"
            else:
                bias = "NEUTRAL_BEARISH"
                confluence = 5
                desc = f"Price ({format_price(symbol, ref_price)}) below VWAP ({format_price(symbol, vwap)}) inside Value Area (VAL: {format_price(symbol, val)}, POC: {format_price(symbol, poc)})"

        return SessionVWAPResult(
            session_name=session_name,
            vwap=round_price(symbol, vwap),
            vah=round_price(symbol, vah),
            val=round_price(symbol, val),
            poc=round_price(symbol, poc),
            current_relation=relation,
            bias_confluence=bias,
            confluence_score=confluence,
            description=desc
        )
