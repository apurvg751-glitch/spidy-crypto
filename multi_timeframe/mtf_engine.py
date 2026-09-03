from typing import Sequence, Optional
from market_data.models import Candle, MultiTimeframeContext
from indicators.moving_averages import calculate_ema, get_trend_bias


class MultiTimeframeEngine:
    """
    Computes multi-timeframe market alignment:
    - 4H = Macro market bias
    - 1H = Intermediate trend / context
    - 15M = Trade execution context
    - 5M = Detailed structure / setup analysis
    Timeframe relationships are parameterized to allow alternative backtesting mappings.
    """

    @staticmethod
    def evaluate(
        symbol: str,
        candles_5m: Sequence[Candle],
        candles_15m: Sequence[Candle],
        candles_1h: Optional[Sequence[Candle]] = None,
        candles_4h: Optional[Sequence[Candle]] = None
    ) -> MultiTimeframeContext:
        candles_1h = candles_1h or []
        candles_4h = candles_4h or []

        # 1. 4H Macro Bias
        if len(candles_4h) >= 15:
            macro_bias = get_trend_bias(candles_4h)
        elif len(candles_1h) >= 15:
            macro_bias = get_trend_bias(candles_1h)
        else:
            macro_bias = get_trend_bias(candles_15m)

        # 2. 1H Intermediate Trend
        if len(candles_1h) >= 15:
            trend_1h = get_trend_bias(candles_1h)
        else:
            trend_1h = get_trend_bias(candles_15m)

        # 3. 15M Execution Context
        exec_context_15m = get_trend_bias(candles_15m)

        # 4. 5M Structure Context
        struct_5m = get_trend_bias(candles_5m)

        # 5. EMA 200 Context (evaluated on 15m / 1h)
        ref_candles = candles_15m if len(candles_15m) >= 30 else candles_5m
        closes = [c.close for c in ref_candles]
        ema200_series = calculate_ema(closes, 200)
        ema200_val = ema200_series[-1] if ema200_series else closes[-1]
        current_close = closes[-1] if closes else 0.0

        if current_close > ema200_val:
            ema200_bias = "Bullish"
        elif current_close < ema200_val:
            ema200_bias = "Bearish"
        else:
            ema200_bias = "Neutral"

        # Alignment Score (0 - 100)
        # 4H = 35 pts, 1H = 30 pts, 15M = 20 pts, EMA 200 = 15 pts
        bull_pts = 0
        bear_pts = 0

        if macro_bias == "Bullish": bull_pts += 35
        elif macro_bias == "Bearish": bear_pts += 35

        if trend_1h == "Bullish": bull_pts += 30
        elif trend_1h == "Bearish": bear_pts += 30

        if exec_context_15m == "Bullish": bull_pts += 20
        elif exec_context_15m == "Bearish": bear_pts += 20

        if ema200_bias == "Bullish": bull_pts += 15
        elif ema200_bias == "Bearish": bear_pts += 15

        alignment_score = max(bull_pts, bear_pts)

        return MultiTimeframeContext(
            symbol=symbol,
            macro_bias_4h=macro_bias,
            trend_1h=trend_1h,
            exec_context_15m=exec_context_15m,
            struct_5m=struct_5m,
            ema200_bias=ema200_bias,
            alignment_score=alignment_score
        )
