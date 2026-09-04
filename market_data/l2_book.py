import time
import logging
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel
import httpx

from config.settings import settings

logger = logging.getLogger("spidy.market_data.l2_book")


class OrderBookLevel(BaseModel):
    price: float
    size: float
    depth: float


class LiquidityWall(BaseModel):
    side: str           # "BID" (Support) or "ASK" (Resistance)
    price: float
    size: float
    distance_pct: float
    is_major: bool = False


class OrderBookAnalysis(BaseModel):
    symbol: str
    timestamp: int
    best_bid: float
    best_ask: float
    spread: float
    spread_bps: float
    total_bid_depth_top20: float
    total_ask_depth_top20: float
    imbalance_ratio_top20: float   # > 1.0 means bids dominate (buy pressure), < 1.0 means asks dominate
    imbalance_bias: str            # "BULLISH_IMBALANCE", "BEARISH_IMBALANCE", "NEUTRAL"
    nearest_bid_wall: Optional[LiquidityWall] = None
    nearest_ask_wall: Optional[LiquidityWall] = None
    top_bids: List[OrderBookLevel] = []
    top_asks: List[OrderBookLevel] = []


class OrderBookEngine:
    """
    Level-2 Depth of Market (DOM) Engine.
    Fetches real-time Level-2 order book snapshots from Delta Exchange India,
    aggregates queue depth, computes Bid/Ask Imbalance ratios, and identifies
    institutional liquidity absorption walls.
    """

    def __init__(self, base_url: Optional[str] = None, cache_ttl_seconds: float = 1.0):
        self.base_url = (base_url or settings.DELTA_REST_URL).rstrip("/")
        self.cache_ttl = cache_ttl_seconds
        self.client = httpx.AsyncClient(verify=False, timeout=6.0)
        self._cache: Dict[str, Tuple[float, OrderBookAnalysis]] = {}

    async def close(self):
        await self.client.aclose()

    async def fetch_l2_book(self, symbol: str) -> Optional[OrderBookAnalysis]:
        """Fetches and analyzes Level-2 Order Book with caching."""
        now = time.time()
        if symbol in self._cache:
            ts, cached = self._cache[symbol]
            if (now - ts) < self.cache_ttl:
                return cached

        url = f"{self.base_url}/v2/l2orderbook/{symbol}"
        try:
            res = await self.client.get(url)
            if res.status_code != 200:
                logger.warning(f"Failed to fetch L2 book for {symbol}: HTTP {res.status_code}")
                return self._cache.get(symbol, (0, None))[1]

            data = res.json()
            if not data.get("success", False):
                return self._cache.get(symbol, (0, None))[1]

            result = data.get("result", {})
            raw_buys = result.get("buy", [])
            raw_sells = result.get("sell", [])

            analysis = self.parse_orderbook(symbol, raw_buys, raw_sells)
            self._cache[symbol] = (now, analysis)
            return analysis

        except Exception as e:
            logger.error(f"Error in fetch_l2_book for {symbol}: {e}")
            return self._cache.get(symbol, (0, None))[1]

    @classmethod
    def parse_orderbook(
        cls,
        symbol: str,
        raw_buys: List[Dict],
        raw_sells: List[Dict],
        depth_levels: int = 20
    ) -> OrderBookAnalysis:
        """Parses raw bid/ask level arrays and calculates DOM metrics."""
        bids: List[OrderBookLevel] = []
        asks: List[OrderBookLevel] = []

        for b in raw_buys[:50]:
            try:
                bids.append(OrderBookLevel(
                    price=float(b["price"]),
                    size=float(b.get("size", 0.0)),
                    depth=float(b.get("depth", 0.0))
                ))
            except (KeyError, ValueError):
                continue

        for a in raw_sells[:50]:
            try:
                asks.append(OrderBookLevel(
                    price=float(a["price"]),
                    size=float(a.get("size", 0.0)),
                    depth=float(a.get("depth", 0.0))
                ))
            except (KeyError, ValueError):
                continue

        best_bid = bids[0].price if bids else 0.0
        best_ask = asks[0].price if asks else 0.0
        mid_price = (best_bid + best_ask) / 2.0 if (best_bid > 0 and best_ask > 0) else max(best_bid, best_ask)

        spread = max(best_ask - best_bid, 0.0) if (best_bid > 0 and best_ask > 0) else 0.0
        spread_bps = (spread / mid_price * 10000.0) if mid_price > 0 else 0.0

        # Aggregate Top-N Depth
        bid_depth = sum(b.size for b in bids[:depth_levels])
        ask_depth = sum(a.size for a in asks[:depth_levels])

        imbalance_ratio = round(bid_depth / max(ask_depth, 1.0), 2)
        if imbalance_ratio >= 1.30:
            bias = "BULLISH_IMBALANCE"
        elif imbalance_ratio <= 0.77:
            bias = "BEARISH_IMBALANCE"
        else:
            bias = "NEUTRAL"

        # Detect Institutional Liquidity Walls (orders >= 2.0x average level size)
        avg_bid_size = (bid_depth / max(len(bids[:depth_levels]), 1)) if bids else 1.0
        avg_ask_size = (ask_depth / max(len(asks[:depth_levels]), 1)) if asks else 1.0

        bid_wall = None
        for b in bids[:30]:
            if b.size >= avg_bid_size * 2.0 and mid_price > 0:
                dist_pct = round((mid_price - b.price) / mid_price * 100.0, 2)
                bid_wall = LiquidityWall(
                    side="BID",
                    price=b.price,
                    size=b.size,
                    distance_pct=dist_pct,
                    is_major=(b.size >= avg_bid_size * 2.5)
                )
                break

        ask_wall = None
        for a in asks[:30]:
            if a.size >= avg_ask_size * 2.0 and mid_price > 0:
                dist_pct = round((a.price - mid_price) / mid_price * 100.0, 2)
                ask_wall = LiquidityWall(
                    side="ASK",
                    price=a.price,
                    size=a.size,
                    distance_pct=dist_pct,
                    is_major=(a.size >= avg_ask_size * 2.5)
                )
                break


        return OrderBookAnalysis(
            symbol=symbol,
            timestamp=int(time.time()),
            best_bid=best_bid,
            best_ask=best_ask,
            spread=round(spread, 4),
            spread_bps=round(spread_bps, 2),
            total_bid_depth_top20=round(bid_depth, 2),
            total_ask_depth_top20=round(ask_depth, 2),
            imbalance_ratio_top20=imbalance_ratio,
            imbalance_bias=bias,
            nearest_bid_wall=bid_wall,
            nearest_ask_wall=ask_wall,
            top_bids=bids[:10],
            top_asks=asks[:10]
        )
