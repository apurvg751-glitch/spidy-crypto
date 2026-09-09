from typing import Optional, Literal
from pydantic import BaseModel
from market_data.models import Candle


class BtcAnchorResult(BaseModel):
    is_allowed: bool
    btc_trend: str
    rejection_reason: str = ""
    reason: str = ""


class BtcAnchorEngine:
    """
    Bitcoin Mother-Ship Directional Lock.
    Prevents altcoins from trading against the dominant BTC liquidity tide.
    """

    @staticmethod
    def evaluate_btc_alignment(
        symbol: str,
        direction: Literal["LONG", "SHORT"],
        btc_candles_15m: list[Candle],
        setup_score: int = 0,
        model_id: str = ""
    ) -> BtcAnchorResult:
        sym = symbol.upper()
        # 1. Bitcoin itself is exempt from altcoin anchor checks
        if sym == "BTCUSD":
            return BtcAnchorResult(
                is_allowed=True,
                btc_trend="SELF",
                reason="BTCUSD trades on its own primary market structure"
            )

        if not btc_candles_15m or len(btc_candles_15m) < 20:
            # Fallback if BTC candles are not yet loaded
            return BtcAnchorResult(
                is_allowed=True,
                btc_trend="UNKNOWN",
                reason="BTC data unavailable; permitting trade with standard confluences"
            )

        # 2. Compute 15M EMA 20 and EMA 50 on BTC
        closes = [c.close for c in btc_candles_15m]
        ema_20 = BtcAnchorEngine._calculate_ema(closes, 20)
        ema_50 = BtcAnchorEngine._calculate_ema(closes, 50) if len(closes) >= 50 else ema_20
        last_close = closes[-1]

        is_btc_bullish = last_close > ema_20 and (ema_20 >= ema_50 * 0.999)
        is_btc_bearish = last_close < ema_20 and (ema_20 <= ema_50 * 1.001)

        btc_trend_label = "BULLISH" if is_btc_bullish else ("BEARISH" if is_btc_bearish else "NEUTRAL")

        # 3. High-Conviction & Divergence Exemption:
        # High-scoring setups (>= 80) and models designed for decoupling/sweeps (M11 Judas, M14 SMT, M10 Sniper)
        # legitimately capture idiosyncratic altcoin alpha even when BTC is flat or mildly biased.
        # Only extreme parabolic moves on BTC (> 1.5% extension from EMA20) veto high-conviction trades.
        is_high_conviction = setup_score >= 80 or model_id in ("MODEL_11", "MODEL_14", "MODEL_10")
        if is_high_conviction:
            btc_ext_pct = abs(last_close - ema_20) / ema_20 if ema_20 > 0 else 0.0
            if btc_ext_pct > 0.015 and model_id != "MODEL_14":
                if direction == "LONG" and is_btc_bearish:
                    return BtcAnchorResult(
                        is_allowed=False,
                        btc_trend=btc_trend_label,
                        rejection_reason=f"BLOCKED BY BTC MACRO ANCHOR: {sym} LONG rejected during extreme parabolic BTC selloff ({last_close:.1f} is {btc_ext_pct*100:.1f}% below EMA20)."
                    )
                if direction == "SHORT" and is_btc_bullish:
                    return BtcAnchorResult(
                        is_allowed=False,
                        btc_trend=btc_trend_label,
                        rejection_reason=f"BLOCKED BY BTC MACRO ANCHOR: {sym} SHORT rejected during extreme parabolic BTC surge ({last_close:.1f} is {btc_ext_pct*100:.1f}% above EMA20)."
                    )

            return BtcAnchorResult(
                is_allowed=True,
                btc_trend=btc_trend_label,
                reason=f"Permitted: High-conviction setup (Score {setup_score}/100, Model {model_id or 'N/A'}) overrides mild BTC anchor bias ({btc_trend_label})"
            )

        # 4. Standard Mother-Ship Anchor Rules (applied to standard/low-conviction setups)
        if direction == "LONG" and is_btc_bearish:
            return BtcAnchorResult(
                is_allowed=False,
                btc_trend=btc_trend_label,
                rejection_reason=f"BLOCKED BY BTC MACRO ANCHOR: {sym} LONG rejected because BTCUSD 15M is trending BEARISH ({last_close:.1f} < EMA20 {ema_20:.1f})."
            )

        if direction == "SHORT" and is_btc_bullish:
            return BtcAnchorResult(
                is_allowed=False,
                btc_trend=btc_trend_label,
                rejection_reason=f"BLOCKED BY BTC MACRO ANCHOR: {sym} SHORT rejected because BTCUSD 15M is trending BULLISH ({last_close:.1f} > EMA20 {ema_20:.1f})."
            )

        return BtcAnchorResult(
            is_allowed=True,
            btc_trend=btc_trend_label,
            reason=f"Permitted: Aligned with BTCUSD 15M market bias ({btc_trend_label})"
        )

    @staticmethod
    def _calculate_ema(values: list[float], period: int) -> float:
        if len(values) < period:
            return sum(values) / len(values)
        k = 2.0 / (period + 1)
        ema = sum(values[:period]) / period
        for val in values[period:]:
            ema = (val * k) + (ema * (1.0 - k))
        return ema
