import time
import logging
from typing import Optional
import httpx

from config.settings import settings
from .models import Candle, Ticker

logger = logging.getLogger("spidy.market_data.rest")


class DeltaRestClient:
    """REST client for fetching Delta Exchange India historical candles and market data."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or settings.DELTA_REST_URL).rstrip("/")
        self.client = httpx.AsyncClient(verify=False, timeout=10.0)

    async def close(self):
        await self.client.aclose()

    async def get_candles(
        self,
        symbol: str,
        resolution: str = "5m",
        limit: int = 150,
        end_time: Optional[int] = None
    ) -> list[Candle]:
        """
        Fetches historical candles from Delta Exchange India.
        Endpoint: /v2/history/candles?symbol=ETHUSD&resolution=5m&start=...&end=...
        """
        end = end_time or int(time.time())
        # Calculate start timestamp based on resolution
        resolution_seconds = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "4h": 14400,
            "1d": 86400,
        }.get(resolution, 300)

        start = end - (limit * resolution_seconds)
        url = f"{self.base_url}/v2/history/candles"
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": start,
            "end": end
        }

        try:
            response = await self.client.get(url, params=params)
            if response.status_code != 200:
                logger.error(f"Delta REST error [{symbol} {resolution}]: HTTP {response.status_code} - {response.text}")
                return []

            data = response.json()
            if not data.get("success", False):
                logger.error(f"Delta REST returned unsuccessful response: {data}")
                return []

            raw_candles = data.get("result", [])
            candles = []
            for item in raw_candles:
                try:
                    c = Candle(
                        time=int(item["time"]),
                        open=float(item["open"]),
                        high=float(item["high"]),
                        low=float(item["low"]),
                        close=float(item["close"]),
                        volume=float(item.get("volume", 0.0)),
                        is_closed=True
                    )
                    candles.append(c)
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning(f"Failed to parse candle item {item}: {e}")
                    continue

            # Delta returns candles descending (latest first) -> sort ascending (oldest first)
            candles.sort(key=lambda x: x.time)

            # Deduplicate by timestamp
            deduped = []
            seen = set()
            for c in candles:
                if c.time not in seen:
                    seen.add(c.time)
                    deduped.append(c)

            return deduped

        except Exception as e:
            logger.error(f"Delta REST request failed [{symbol} {resolution}]: {e}")
            return []

    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """Fetches latest ticker/mark price for a symbol."""
        url = f"{self.base_url}/v2/tickers/{symbol}"
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                data = response.json()
                if data.get("success", False):
                    res = data.get("result", {})
                    return Ticker(
                        symbol=symbol,
                        mark_price=float(res.get("mark_price") or res.get("close") or 0.0),
                        last_price=float(res.get("close") or res.get("mark_price") or 0.0),
                        volume_24h=float(res.get("volume") or 0.0),
                        change_24h=float(res.get("change_24h") or 0.0),
                        timestamp=int(time.time())
                    )
        except Exception as e:
            logger.debug(f"Failed to fetch ticker for {symbol}: {e}")
        return None
