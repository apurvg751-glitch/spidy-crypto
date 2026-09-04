from typing import List, Optional
from pydantic import BaseModel
from market_data.models import Candle


class SMTResult(BaseModel):
    detected: bool
    divergence_type: str       # "BEARISH_SMT", "BULLISH_SMT", "NONE"
    leader_symbol: Optional[str] = None
    laggard_symbol: Optional[str] = None
    description: str


class SMTDivergenceEngine:
    """
    Smart Money Tool (SMT) Intermarket Divergence Engine.
    Correlates BTCUSD and ETHUSD swing highs and swing lows to detect institutional accumulation and distribution.
    - Bearish SMT: BTC makes Higher High, ETH fails (makes Lower High) -> Smart Money distributing.
    - Bullish SMT: BTC makes Lower Low, ETH fails (makes Higher Low) -> Smart Money accumulating.
    """

    @classmethod
    def evaluate(
        cls,
        candles_btc: List[Candle],
        candles_eth: List[Candle],
        lookback: int = 24,
        direction: Optional[str] = None
    ) -> SMTResult:
        if not candles_btc or not candles_eth or len(candles_btc) < 4 or len(candles_eth) < 4:
            return SMTResult(
                detected=False,
                divergence_type="NONE",
                description="Insufficient synchronized candle data for SMT evaluation."
            )

        btc_window = candles_btc[-lookback:]
        eth_window = candles_eth[-lookback:]

        # Split window into Prior Half and Recent Half
        mid = len(btc_window) // 2
        btc_prior, btc_recent = btc_window[:mid], btc_window[mid:]
        eth_prior, eth_recent = eth_window[:mid], eth_window[mid:]

        btc_h1, btc_h2 = max(c.high for c in btc_prior), max(c.high for c in btc_recent)
        btc_l1, btc_l2 = min(c.low for c in btc_prior), min(c.low for c in btc_recent)

        eth_h1, eth_h2 = max(c.high for c in eth_prior), max(c.high for c in eth_recent)
        eth_l1, eth_l2 = min(c.low for c in eth_prior), min(c.low for c in eth_recent)

        # 1. Check Bearish SMT: BTC higher high, ETH lower high (or vice versa)
        if (btc_h2 > btc_h1 and eth_h2 < eth_h1):
            return SMTResult(
                detected=True,
                divergence_type="BEARISH_SMT",
                leader_symbol="BTCUSD",
                laggard_symbol="ETHUSD",
                description="Bearish SMT Divergence: BTC made Higher High while ETH made Lower High (Institutional Distribution)."
            )
        elif (eth_h2 > eth_h1 and btc_h2 < btc_h1):
            return SMTResult(
                detected=True,
                divergence_type="BEARISH_SMT",
                leader_symbol="ETHUSD",
                laggard_symbol="BTCUSD",
                description="Bearish SMT Divergence: ETH made Higher High while BTC made Lower High (Institutional Distribution)."
            )

        # 2. Check Bullish SMT: BTC lower low, ETH higher low (or vice versa)
        if (btc_l2 < btc_l1 and eth_l2 > eth_l1):
            return SMTResult(
                detected=True,
                divergence_type="BULLISH_SMT",
                leader_symbol="BTCUSD",
                laggard_symbol="ETHUSD",
                description="Bullish SMT Divergence: BTC made Lower Low while ETH refused to drop (Higher Low - Smart Money Accumulation)."
            )
        elif (eth_l2 < eth_l1 and btc_l2 > btc_l1):
            return SMTResult(
                detected=True,
                divergence_type="BULLISH_SMT",
                leader_symbol="ETHUSD",
                laggard_symbol="BTCUSD",
                description="Bullish SMT Divergence: ETH made Lower Low while BTC held Higher Low (Smart Money Accumulation)."
            )

        return SMTResult(
            detected=False,
            divergence_type="NONE",
            description="Correlated Market Structure: BTC and ETH moving in lockstep."
        )
