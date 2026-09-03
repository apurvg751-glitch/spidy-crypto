import asyncio
import json
import logging
import time
from typing import Callable, Optional
import websockets

from config.settings import settings
from .models import Candle, Ticker

logger = logging.getLogger("spidy.market_data.ws")


class DeltaWsClient:
    """WebSocket client for Delta Exchange India real-time candles and ticker streams."""

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        on_candle: Optional[Callable[[str, str, Candle], None]] = None,
        on_ticker: Optional[Callable[[Ticker], None]] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
    ):
        self.symbols = symbols or settings.SYMBOLS
        self.ws_urls = [settings.DELTA_WS_URL, settings.DELTA_WS_FALLBACK_URL]
        self.on_candle = on_candle
        self.on_ticker = on_ticker
        self.on_status_change = on_status_change

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_url_index = 0
        self.connection_status = "DISCONNECTED"

    def _set_status(self, status: str):
        self.connection_status = status
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception as e:
                logger.error(f"Error in status change callback: {e}")

    async def start(self):
        """Starts WebSocket client in background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stops WebSocket client gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._set_status("DISCONNECTED")

    async def _run_loop(self):
        retry_delay = 2
        max_retry_delay = 30

        while self._running:
            url = self.ws_urls[self._current_url_index % len(self.ws_urls)]
            self._set_status("CONNECTING")
            logger.info(f"Connecting to Delta Exchange WS: {url}")

            try:
                import ssl
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

                async with websockets.connect(
                    url,
                    ssl=ssl_context,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self._set_status("CONNECTED")
                    logger.info(f"Connected to Delta WS: {url}")
                    retry_delay = 2  # reset delay on successful connection

                    # Subscribe to candlesticks and ticker
                    sub_msg = {
                        "type": "subscribe",
                        "payload": {
                            "channels": [
                                {"name": "candlesticks_5m", "symbols": self.symbols},
                                {"name": "candlesticks_15m", "symbols": self.symbols},
                                {"name": "ticker", "symbols": self.symbols}
                            ]
                        }
                    }
                    await ws.send(json.dumps(sub_msg))

                    # Ping task
                    ping_task = asyncio.create_task(self._ping_worker(ws))

                    try:
                        async for message in ws:
                            if not self._running:
                                break
                            self._handle_message(message)
                    finally:
                        ping_task.cancel()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Delta WS connection failed or lost ({url}): {e}")
                self._current_url_index += 1  # rotate url on error
                self._set_status("RECONNECTING")

            if self._running:
                logger.info(f"Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, max_retry_delay)

    async def _ping_worker(self, ws):
        """Periodically sends Delta WS ping."""
        while self._running:
            try:
                await asyncio.sleep(25)
                await ws.send(json.dumps({"type": "ping"}))
            except Exception:
                break

    def _handle_message(self, raw_message: str):
        try:
            msg = json.loads(raw_message)
        except Exception:
            return

        msg_type = msg.get("type")
        if msg_type == "pong" or msg_type == "heartbeat":
            return

        channel = msg.get("channel") or ""
        # Delta candlestick channel format: candlesticks_5m or candlesticks_15m
        if channel.startswith("candlesticks_"):
            resolution = channel.replace("candlesticks_", "")
            symbol = msg.get("symbol")
            data = msg.get("candle") or msg
            if symbol and self.on_candle:
                try:
                    c = Candle(
                        time=int(data.get("time", time.time())),
                        open=float(data["open"]),
                        high=float(data["high"]),
                        low=float(data["low"]),
                        close=float(data["close"]),
                        volume=float(data.get("volume", 0.0)),
                        is_closed=bool(data.get("is_closed", False))
                    )
                    self.on_candle(symbol, resolution, c)
                except Exception as e:
                    logger.debug(f"Failed parsing WS candle {msg}: {e}")

        elif channel == "ticker" or msg_type == "v2/ticker":
            symbol = msg.get("symbol")
            if symbol and self.on_ticker:
                try:
                    t = Ticker(
                        symbol=symbol,
                        mark_price=float(msg.get("mark_price") or msg.get("close") or 0.0),
                        last_price=float(msg.get("close") or msg.get("mark_price") or 0.0),
                        volume_24h=float(msg.get("volume") or 0.0),
                        change_24h=float(msg.get("change_24h") or 0.0),
                        timestamp=int(time.time())
                    )
                    self.on_ticker(t)
                except Exception as e:
                    logger.debug(f"Failed parsing WS ticker {msg}: {e}")
