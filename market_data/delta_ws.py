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

                    # Subscribe to official Delta Exchange India candlestick streams
                    sub_msg = {
                        "type": "subscribe",
                        "payload": {
                            "channels": [
                                {"name": "candlestick_5m", "symbols": self.symbols},
                                {"name": "candlestick_15m", "symbols": self.symbols},
                                {"name": "candlestick_1h", "symbols": self.symbols}
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

        msg_type = msg.get("type") or ""
        if msg_type in ("pong", "heartbeat", "subscriptions"):
            return

        channel = msg.get("channel") or msg_type or ""
        # Delta candlestick channel format: candlestick_5m, candlestick_15m, candlestick_1h
        if channel.startswith("candlestick_") or channel.startswith("candlesticks_"):
            resolution = channel.replace("candlestick_", "").replace("candlesticks_", "")
            symbol = msg.get("symbol") or msg.get("sy")
            data = msg.get("candle") or msg
            if symbol:
                try:
                    open_p = float(data.get("open") if data.get("open") is not None else data.get("o", 0.0))
                    high_p = float(data.get("high") if data.get("high") is not None else data.get("h", 0.0))
                    low_p = float(data.get("low") if data.get("low") is not None else data.get("l", 0.0))
                    close_p = float(data.get("close") if data.get("close") is not None else data.get("c", 0.0))
                    vol = float(data.get("volume") if data.get("volume") is not None else data.get("v", 0.0))
                    
                    raw_time = data.get("time") or data.get("cst") or (data.get("ts", 0) // 1000000) or int(time.time())
                    if raw_time > 1000000000000000:
                        raw_time = raw_time // 1000000
                    elif raw_time > 1000000000000:
                        raw_time = raw_time // 1000

                    c = Candle(
                        time=int(raw_time),
                        open=open_p,
                        high=high_p,
                        low=low_p,
                        close=close_p,
                        volume=vol,
                        is_closed=bool(data.get("is_closed", False))
                    )
                    if self.on_candle and close_p > 0:
                        self.on_candle(symbol, resolution, c)

                    # Continuous real-time price tick dispatch
                    if self.on_ticker and close_p > 0:
                        t = Ticker(
                            symbol=symbol,
                            mark_price=close_p,
                            last_price=close_p,
                            volume_24h=vol,
                            change_24h=0.0,
                            timestamp=int(time.time())
                        )
                        self.on_ticker(t)
                except Exception as e:
                    logger.debug(f"Failed parsing WS candle {msg}: {e}")
