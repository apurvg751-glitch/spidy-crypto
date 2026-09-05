import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("spidy.order_flow")


class OrderFlowEngine:
    """
    Cumulative Volume Delta (CVD) & Order Flow Engine.
    Quantifies market aggressor buying vs selling volume to identify
    whale absorption and institutional volume divergences.
    """

    @staticmethod
    def calculate_cvd(trades_or_candles: List[Dict[str, Any]]) -> List[float]:
        """
        Calculates cumulative delta array from candle volume and wick delta approximations,
        or raw tick buy/sell volumes.
        """
        cvd_series = []
        cumulative = 0.0

        for bar in trades_or_candles:
            # If raw tick with side
            if "side" in bar and "size" in bar:
                size = float(bar["size"])
                delta = size if bar["side"].upper() == "BUY" else -size
            else:
                # Candle approximation: (Close - Open) / (High - Low) * Volume
                o = float(bar.get("open", bar.get("o", 1.0)))
                c = float(bar.get("close", bar.get("c", 1.0)))
                h = float(bar.get("high", bar.get("h", 1.0)))
                l = float(bar.get("low", bar.get("l", 1.0)))
                v = float(bar.get("volume", bar.get("v", 100.0)))
                rng = max(h - l, 1e-4)
                ratio = (c - o) / rng
                delta = ratio * v

            cumulative += delta
            cvd_series.append(round(cumulative, 2))

        return cvd_series

    @staticmethod
    def detect_cvd_divergence(
        prices: List[float],
        cvd: List[float]
    ) -> Tuple[bool, str]:
        """
        Detects structural divergence between price and CVD:
        - Bullish Absorption: Price makes lower low, but CVD makes higher low.
        - Bearish Distribution: Price makes higher high, but CVD makes lower high.
        """
        if len(prices) < 4 or len(cvd) < 4:
            return False, "INSUFFICIENT_DATA"

        p_prev, p_curr = prices[-4], prices[-1]
        c_prev, c_curr = cvd[-4], cvd[-1]

        # Bullish CVD Divergence (Whales silently buying into falling prices)
        if p_curr < p_prev and c_curr > c_prev:
            return True, "BULLISH_CVD_ABSORPTION"

        # Bearish CVD Divergence (Whales dumping into rising prices)
        elif p_curr > p_prev and c_curr < c_prev:
            return True, "BEARISH_CVD_DISTRIBUTION"

        return False, "NO_DIVERGENCE"
