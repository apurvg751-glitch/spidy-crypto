import time
import logging
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel
import httpx

from config.settings import settings

logger = logging.getLogger("spidy.market_data.derivatives_intel")


class LiquidationCluster(BaseModel):
    leverage: int           # 25, 50, 100
    side: str               # "SHORT_LIQUIDATION" (Buy Magnet above price) or "LONG_LIQUIDATION" (Sell Magnet below price)
    estimated_price: float
    distance_pct: float
    intensity: str          # "HIGH", "EXTREME", "MEDIUM"
    description: str


class DerivativesIntel(BaseModel):
    symbol: str
    timestamp: int
    funding_rate: float
    predicted_funding_rate: float
    annualized_funding_pct: float
    sentiment: str          # "EXTREME_LONG_CROWDED", "EXTREME_SHORT_CROWDED", "NEUTRAL_BALANCED"
    squeeze_potential: str  # "SHORT_SQUEEZE_PRIME", "LONG_SQUEEZE_PRIME", "NONE"
    liquidation_clusters: List[LiquidationCluster] = []
    primary_liquidity_magnet: Optional[LiquidationCluster] = None


class DerivativesIntelEngine:
    """
    Derivatives Intelligence & Liquidation Heatmap Engine.
    Tracks live 8-hour and predicted funding rates, identifies crowded retail positioning,
    and models high-leverage (25x / 50x / 100x) liquidation clusters as institutional liquidity magnets.
    """

    def __init__(self, base_url: Optional[str] = None, cache_ttl_seconds: float = 3.0):
        self.base_url = (base_url or settings.DELTA_REST_URL).rstrip("/")
        self.cache_ttl = cache_ttl_seconds
        self.client = httpx.AsyncClient(verify=False, timeout=6.0)
        self._cache: Dict[str, Tuple[float, DerivativesIntel]] = {}
        self._all_tickers_cache: Tuple[float, Dict[str, Dict]] = (0.0, {})

    async def close(self):
        await self.client.aclose()

    async def fetch_derivatives_intel(
        self,
        symbol: str,
        current_price: float,
        recent_high: Optional[float] = None,
        recent_low: Optional[float] = None
    ) -> DerivativesIntel:
        """Fetches ticker funding rates and constructs the liquidation heatmap."""
        now = time.time()
        if symbol in self._cache:
            ts, cached = self._cache[symbol]
            if (now - ts) < self.cache_ttl:
                return cached

        raw_ticker = await self._get_ticker_data(symbol)
        funding = float(raw_ticker.get("funding_rate", 0.0001) or 0.0001)
        pred_funding = float(raw_ticker.get("predicted_funding_rate", funding) or funding)

        annualized = round(funding * 3 * 365 * 100.0, 2)  # 3 funding periods per day (8h)

        # Classify Retail Crowd Sentiment
        if funding >= 0.0005:
            sentiment = "EXTREME_LONG_CROWDED"
            squeeze = "LONG_SQUEEZE_PRIME"
        elif funding <= -0.0003:
            sentiment = "EXTREME_SHORT_CROWDED"
            squeeze = "SHORT_SQUEEZE_PRIME"
        else:
            sentiment = "NEUTRAL_BALANCED"
            squeeze = "NONE"

        # Model Liquidation Clusters based on current price & swing anchors
        ref_high = recent_high or (current_price * 1.015)
        ref_low = recent_low or (current_price * 0.985)

        clusters = self.calculate_liquidation_clusters(current_price, ref_high, ref_low)

        # Primary Magnet is nearest high-intensity cluster in direction of squeeze/bias
        primary_magnet = None
        if clusters:
            primary_magnet = min(clusters, key=lambda c: abs(c.distance_pct))

        intel = DerivativesIntel(
            symbol=symbol,
            timestamp=int(now),
            funding_rate=round(funding, 6),
            predicted_funding_rate=round(pred_funding, 6),
            annualized_funding_pct=annualized,
            sentiment=sentiment,
            squeeze_potential=squeeze,
            liquidation_clusters=clusters,
            primary_liquidity_magnet=primary_magnet
        )

        self._cache[symbol] = (now, intel)
        return intel

    async def _get_ticker_data(self, symbol: str) -> Dict:
        now = time.time()
        ts, cached_map = self._all_tickers_cache
        if (now - ts) < 2.0 and symbol in cached_map:
            return cached_map[symbol]

        try:
            url = f"{self.base_url}/v2/tickers"
            res = await self.client.get(url)
            if res.status_code == 200:
                data = res.json()
                if data.get("success", False):
                    new_map = {item.get("symbol"): item for item in data.get("result", []) if item.get("symbol")}
                    self._all_tickers_cache = (now, new_map)
                    return new_map.get(symbol, {})
        except Exception as e:
            logger.warning(f"Error fetching /v2/tickers: {e}")

        return self._all_tickers_cache[1].get(symbol, {})

    @staticmethod
    def calculate_liquidation_clusters(
        current_price: float,
        swing_high: float,
        swing_low: float
    ) -> List[LiquidationCluster]:
        """
        Calculates mathematical retail liquidation price points:
        - 100x shorts liquidate ~0.8% - 1.0% above swing high
        - 50x shorts liquidate ~1.8% - 2.0% above swing high
        - 25x shorts liquidate ~3.8% - 4.0% above swing high
        - 100x longs liquidate ~0.8% - 1.0% below swing low
        - 50x longs liquidate ~1.8% - 2.0% below swing low
        - 25x longs liquidate ~3.8% - 4.0% below swing low
        """
        if current_price <= 0:
            return []

        clusters: List[LiquidationCluster] = []

        # Short Liquidations (Buy-Side Liquidity Pool Above)
        short_levs = [(100, 0.009, "EXTREME"), (50, 0.019, "HIGH"), (25, 0.038, "MEDIUM")]
        for lev, factor, intensity in short_levs:
            liq_price = max(swing_high * (1.0 + factor), current_price * (1.0 + (factor * 0.7)))
            dist_pct = round((liq_price - current_price) / current_price * 100.0, 2)
            clusters.append(LiquidationCluster(
                leverage=lev,
                side="SHORT_LIQUIDATION",
                estimated_price=round(liq_price, 2),
                distance_pct=dist_pct,
                intensity=intensity,
                description=f"{lev}x Short Liquidation Pool (+{dist_pct:.2f}% above market)"
            ))

        # Long Liquidations (Sell-Side Liquidity Pool Below)
        long_levs = [(100, 0.009, "EXTREME"), (50, 0.019, "HIGH"), (25, 0.038, "MEDIUM")]
        for lev, factor, intensity in long_levs:
            liq_price = min(swing_low * (1.0 - factor), current_price * (1.0 - (factor * 0.7)))
            dist_pct = round((liq_price - current_price) / current_price * 100.0, 2)
            clusters.append(LiquidationCluster(
                leverage=lev,
                side="LONG_LIQUIDATION",
                estimated_price=round(liq_price, 2),
                distance_pct=dist_pct,
                intensity=intensity,
                description=f"{lev}x Long Liquidation Pool ({dist_pct:.2f}% below market)"
            ))

        return clusters
