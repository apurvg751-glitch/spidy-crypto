import asyncio
import logging
import time
from typing import Callable, Optional

from config.settings import settings
from .models import Candle, Ticker, MarketState
from .delta_rest import DeltaRestClient
from .delta_ws import DeltaWsClient

logger = logging.getLogger("spidy.market_data.feed")


class FeedManager:
    """
    Central Market Data Feed Manager.
    Aggregates live WS updates and REST backfills for ETHUSD, BTCUSD, and SOLUSD.
    Provides duplicate protection, stale data detection, and automatic REST fallback.
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        on_candle_closed: Optional[Callable[[str, str, Candle], None]] = None,
        on_tick: Optional[Callable[[str, float], None]] = None
    ):
        # Always include BTCUSD in feeds as the Mother-Ship macro anchor
        raw_symbols = list(symbols or settings.SYMBOLS)
        if "BTCUSD" not in raw_symbols:
            raw_symbols.append("BTCUSD")
        self.symbols = raw_symbols
        self.on_candle_closed = on_candle_closed
        self.on_tick = on_tick

        self.rest_client = DeltaRestClient()
        self.markets: dict[str, MarketState] = {
            s: MarketState(symbol=s) for s in self.symbols
        }

        self.ws_client = DeltaWsClient(
            symbols=self.symbols,
            on_candle=self._handle_ws_candle,
            on_ticker=self._handle_ws_ticker,
            on_status_change=self._handle_ws_status
        )

        self._running = False
        self._fallback_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize data feeds: initial REST backfill + live WS connection."""
        if self._running:
            return
        self._running = True

        logger.info("Initializing Market Data Feed Manager...")
        # 1. Historical backfill via REST for all symbols
        await self.backfill_all()

        # 2. Start WebSocket client
        await self.ws_client.start()

        # 3. Start periodic REST fallback and stale checker
        self._fallback_task = asyncio.create_task(self._monitor_and_fallback_loop())
        logger.info("Feed Manager operational.")

    async def stop(self):
        self._running = False
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()
        await self.ws_client.stop()
        await self.rest_client.close()
        logger.info("Feed Manager stopped.")

    async def backfill_all(self, limit: int = 150):
        """Backfills historical candles for all symbols and timeframes."""
        logger.info(f"Backfilling historical candles (limit={limit}) via Delta REST...")
        for symbol in self.symbols:
            # 5m candles
            c5 = await self.rest_client.get_candles(symbol, resolution="5m", limit=limit)
            if c5:
                self.markets[symbol].candles_5m = c5
                self.markets[symbol].current_price = c5[-1].close
                self.markets[symbol].last_update_ts = c5[-1].time
                logger.info(f"Loaded {len(c5)} 5m candles for {symbol}. Latest price: {c5[-1].close}")

            # 15m candles
            c15 = await self.rest_client.get_candles(symbol, resolution="15m", limit=limit)
            if c15:
                self.markets[symbol].candles_15m = c15
                logger.info(f"Loaded {len(c15)} 15m candles for {symbol}.")

            # 1h candles
            c1h = await self.rest_client.get_candles(symbol, resolution="1h", limit=min(limit, 80))
            if c1h:
                self.markets[symbol].candles_1h = c1h
                logger.info(f"Loaded {len(c1h)} 1h candles for {symbol}.")

            # 4h candles
            c4h = await self.rest_client.get_candles(symbol, resolution="4h", limit=min(limit, 50))
            if c4h:
                self.markets[symbol].candles_4h = c4h
                logger.info(f"Loaded {len(c4h)} 4h candles for {symbol}.")

            # Update MTF context
            from multi_timeframe.mtf_engine import MultiTimeframeEngine
            self.markets[symbol].mtf_context = MultiTimeframeEngine.evaluate(
                symbol,
                self.markets[symbol].candles_5m,
                self.markets[symbol].candles_15m,
                self.markets[symbol].candles_1h,
                self.markets[symbol].candles_4h
            )

            # Update ticker / stale status
            self._check_stale_status(symbol)

    def _handle_ws_candle(self, symbol: str, resolution: str, candle: Candle):
        if symbol not in self.markets:
            return

        m = self.markets[symbol]
        if resolution == "5m":
            candle_list = m.candles_5m
        elif resolution == "15m":
            candle_list = m.candles_15m
        elif resolution == "1h":
            candle_list = m.candles_1h
        elif resolution == "4h":
            candle_list = m.candles_4h
        else:
            candle_list = m.candles_5m

        # Duplicate protection & candle update
        if not candle_list:
            candle_list.append(candle)
        else:
            last = candle_list[-1]
            if candle.time == last.time:
                # Update current active bar
                candle_list[-1] = candle
            elif candle.time > last.time:
                # Prior candle is now finalized
                last.is_closed = True
                candle_list.append(candle)
                if len(candle_list) > settings.MAX_STORED_CANDLES:
                    candle_list.pop(0)

                # Trigger closed candle callback
                if self.on_candle_closed:
                    try:
                        self.on_candle_closed(symbol, resolution, last)
                    except Exception as e:
                        logger.error(f"Error in on_candle_closed callback: {e}")

        # Update market metadata only if candle is current/newer
        if candle.time >= m.last_update_ts:
            m.current_price = candle.close
            m.last_update_ts = int(time.time())
            m.is_stale = False

    def _handle_ws_ticker(self, ticker: Ticker):
        if ticker.symbol in self.markets:
            m = self.markets[ticker.symbol]
            m.current_price = ticker.last_price
            m.last_update_ts = int(time.time())
            m.is_stale = False
            if self.on_tick:
                try:
                    self.on_tick(ticker.symbol, ticker.last_price)
                except Exception as e:
                    logger.error(f"Error in on_tick callback: {e}")

    def _handle_ws_status(self, status: str):
        for m in self.markets.values():
            m.connection_status = status

    def _check_stale_status(self, symbol: str) -> bool:
        """Evaluates whether market data for the symbol is stale."""
        m = self.markets.get(symbol)
        if not m or not m.candles_5m:
            return True

        now = int(time.time())
        # Check either last_update_ts or latest candle time
        latest_candle_time = m.candles_5m[-1].time
        age = now - latest_candle_time

        is_stale = age > settings.STALE_DATA_THRESHOLD_SECONDS
        m.is_stale = is_stale
        return is_stale

    async def _monitor_and_fallback_loop(self):
        """Periodic background monitor for stale data and fallback polling."""
        while self._running:
            try:
                await asyncio.sleep(settings.REST_POLL_INTERVAL_SECONDS)
                ws_connected = self.ws_client.connection_status == "CONNECTED"

                for symbol in self.symbols:
                    m = self.markets[symbol]
                    stale = self._check_stale_status(symbol)

                    # If WS disconnected or data is stale, fallback to REST polling
                    if not ws_connected or stale:
                        m.connection_status = "REST_FALLBACK" if not ws_connected else "STALE"
                        logger.debug(f"Triggering REST fallback for {symbol} (WS: {self.ws_client.connection_status}, Stale: {stale})")
                        
                        # 1. Fetch live real-time ticker directly
                        live_ticker = await self.rest_client.get_ticker(symbol)
                        if live_ticker:
                            self._handle_ws_ticker(live_ticker)

                        # 2. Update candles
                        c5 = await self.rest_client.get_candles(symbol, resolution="5m", limit=5)
                        if c5:
                            for c in c5:
                                self._handle_ws_candle(symbol, "5m", c)
                            m.is_stale = False

                        c15 = await self.rest_client.get_candles(symbol, resolution="15m", limit=5)
                        if c15:
                            for c in c15:
                                self._handle_ws_candle(symbol, "15m", c)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor/fallback loop: {e}")

    def get_market_state(self, symbol: str) -> Optional[MarketState]:
        return self.markets.get(symbol)

    def get_all_states(self) -> dict[str, MarketState]:
        return self.markets
