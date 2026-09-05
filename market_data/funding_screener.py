import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("spidy.funding_screener")


class FundingRateScreener:
    """
    Delta Exchange India Perpetual Funding Rate Monitor.
    Tracks 8-hour funding rates across all 6 crypto markets, converts to annualized APR %,
    and protects against paying exorbitant carry fees on open trades.
    """

    # Baseline mock/cached funding rates for resilience
    DEFAULT_RATES = {
        "BTCUSD": 0.0001,   # +0.01% per 8h (+10.95% APR)
        "ETHUSD": 0.0001,   # +0.01% per 8h (+10.95% APR)
        "SOLUSD": 0.0002,   # +0.02% per 8h (+21.9% APR)
        "BNBUSD": 0.0001,   # +0.01% per 8h
        "XRPUSD": 0.00015,  # +0.015% per 8h
        "AVAXUSD": 0.0002   # +0.02% per 8h
    }

    @staticmethod
    def analyze_funding(symbol: str, raw_8h_rate: Optional[float] = None) -> Dict[str, Any]:
        """
        Analyzes 8h funding rate and provides sentiment & directional warning.
        Rate of +0.0001 = 0.01% per 8h.
        """
        rate = raw_8h_rate if raw_8h_rate is not None else FundingRateScreener.DEFAULT_RATES.get(symbol.upper(), 0.0001)
        rate_pct = rate * 100.0
        annualized_apr = rate_pct * 3.0 * 365.0  # 3 funding settlements per day

        if rate > 0.0008:
            status = "EXTREME_POSITIVE"
            warning = "Longs paying heavy fee (+87%+ APR). High risk of long liquidation cascade."
            recommendation = "FAVOR_SHORTS"
        elif rate > 0.0003:
            status = "MODERATE_POSITIVE"
            warning = "Bullish tilt. Longs paying moderate carry."
            recommendation = "NEUTRAL"
        elif rate < -0.0005:
            status = "EXTREME_NEGATIVE"
            warning = "Shorts heavily overcrowded (-54% APR). High probability of short squeeze bounce."
            recommendation = "FAVOR_LONGS"
        elif rate < -0.0002:
            status = "MODERATE_NEGATIVE"
            warning = "Bearish crowd tilt. Shorts paying carry fee."
            recommendation = "NEUTRAL"
        else:
            status = "BALANCED"
            warning = "Funding in equilibrium. Safe for both Long & Short execution."
            recommendation = "BALANCED"

        return {
            "symbol": symbol.upper(),
            "rate_8h": rate,
            "rate_8h_pct": round(rate_pct, 4),
            "annualized_apr_pct": round(annualized_apr, 2),
            "status": status,
            "warning": warning,
            "recommendation": recommendation
        }
