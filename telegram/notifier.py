import logging
from typing import Any, Optional
import httpx

from config.settings import settings
from storage.database import Database
from .formatter import format_main_alert, format_lifecycle_alert

logger = logging.getLogger("spidy.telegram")


def get_trade_inline_keyboard() -> dict[str, Any]:
    """Returns interactive inline keyboard buttons for remote trade control."""
    return {
        "inline_keyboard": [
            [
                {"text": "🎯 Move SL to Breakeven", "callback_data": "CMD_BE"},
                {"text": "💰 Close 50% Partial TP", "callback_data": "CMD_PARTIAL"}
            ],
            [
                {"text": "🛑 Emergency Close Trade", "callback_data": "CMD_CLOSE"},
                {"text": "⚡ Instant Status Check", "callback_data": "CMD_STATUS"}
            ],
            [
                {"text": "📖 Daily Trade Journal", "callback_data": "CMD_JOURNAL"}
            ]
        ]
    }


class TelegramNotifier:
    """Dispatches deterministic alerts to Telegram with interactive buttons and persistent duplicate blocking."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        db: Optional[Database] = None
    ):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.db = db or Database()
        self.client = httpx.AsyncClient(verify=False, timeout=15.0)

    async def close(self):
        await self.client.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send_message(self, text: str, reply_markup: Optional[dict[str, Any]] = None) -> bool:
        """Sends raw markdown/text message to the configured Telegram chat with optional buttons."""
        if not self.is_configured:
            logger.info("Telegram notification skipped: Bot token or Chat ID not configured.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        keyboard = reply_markup if reply_markup is not None else get_trade_inline_keyboard()
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "reply_markup": keyboard
        }

        try:
            res = await self.client.post(url, json=payload)
            if res.status_code == 200:
                logger.info("Telegram message delivered successfully.")
                return True
            else:
                logger.warning(f"Telegram API responded with HTTP {res.status_code}: {res.text}. Retrying with plain text.")
                payload.pop("parse_mode", None)
                res2 = await self.client.post(url, json=payload)
                if res2.status_code == 200:
                    logger.info("Telegram message delivered via plain text fallback.")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to deliver Telegram message: {e}")
            return False

    async def send_trade_detected_alert(self, setup_dict: dict[str, Any]) -> bool:
        """Sends primary trade detection alert with interactive control buttons."""
        setup_id = setup_dict.get("id")
        coin = setup_dict.get("coin", "")

        if not setup_id:
            return False

        # Anti-spam: check if this setup was already alerted
        alert_id = f"MAIN_{setup_id}"
        if self.db.is_alert_sent(alert_id):
            logger.info(f"Duplicate alert blocked by anti-spam guard: {alert_id}")
            return False

        import time
        now = int(time.time())
        last_sent = getattr(self, "_last_alert_time", {}).get(coin, 0)
        if (now - last_sent) < 300:
            logger.info(f"Telegram anti-spam active for {coin} ({now - last_sent}s / 300s). Alert throttled.")
            return False
        if not hasattr(self, "_last_alert_time"):
            self._last_alert_time = {}
        self._last_alert_time[coin] = now

        message = format_main_alert(setup_dict)
        buttons = get_trade_inline_keyboard()
        success = await self.send_message(message, reply_markup=buttons)

        # Mark sent in DB whether delivered or simulated so it never spams
        self.db.record_alert_sent(alert_id, coin, "MAIN_ALERT")
        return success

    async def send_trade_lifecycle_update(
        self,
        coin: str,
        direction: str,
        status: str,
        price: float,
        setup_id: str,
        details: str = ""
    ) -> bool:
        """Sends lifecycle status updates (ACTIVE, TARGET HIT, STOPPED, CANCELLED, COMPLETED)."""
        alert_id = f"{status}_{setup_id}"
        if self.db.is_alert_sent(alert_id):
            logger.info(f"Duplicate lifecycle alert blocked: {alert_id}")
            return False

        message = format_lifecycle_alert(coin, direction, status, price, details)
        buttons = get_trade_inline_keyboard()
        success = await self.send_message(message, reply_markup=buttons)

        self.db.record_alert_sent(alert_id, coin, status)
        return success
