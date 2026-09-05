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

    async def send_photo(
        self,
        photo_bytes: bytes,
        caption: str = "",
        reply_markup: Optional[dict[str, Any]] = None
    ) -> bool:
        """Sends an HD chart image to Telegram with optional caption and interactive buttons."""
        if not self.is_configured or not photo_bytes:
            return False

        import json
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        keyboard = reply_markup if reply_markup is not None else get_trade_inline_keyboard()

        data = {
            "chat_id": self.chat_id,
            "caption": caption,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(keyboard)
        }
        files = {
            "photo": ("spidy_chart.png", photo_bytes, "image/png")
        }

        try:
            res = await self.client.post(url, data=data, files=files)
            if res.status_code == 200:
                logger.info("Telegram HD Chart Photo delivered successfully.")
                return True
            else:
                logger.warning(f"Telegram sendPhoto HTTP {res.status_code}: {res.text}. Falling back to text.")
                return await self.send_message(caption, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"Failed to deliver Telegram chart photo: {e}")
            return await self.send_message(caption, reply_markup=keyboard)

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

        message = format_main_alert(setup_dict)
        buttons = get_trade_inline_keyboard()

        # Generate and deliver HD Candlestick Chart
        try:
            from telegram.chart_generator import generate_trade_chart
            chart_bytes = generate_trade_chart(
                symbol=coin,
                direction=setup_dict.get("direction", "LONG"),
                entry=float(setup_dict.get("entry", 0.0)),
                stop_loss=float(setup_dict.get("stop_loss", 0.0)),
                target_1=float(setup_dict.get("target_1", 0.0)),
                target_2=float(setup_dict.get("target_2", 0.0)),
                candles=setup_dict.get("candles")
            )
            success = await self.send_photo(photo_bytes=chart_bytes, caption=message, reply_markup=buttons)
        except Exception as e:
            logger.warning(f"Chart generation error, delivering text alert: {e}")
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
        details: str = "",
        achieved_r: Optional[float] = None,
        pnl: Optional[float] = None,
        entry: Optional[float] = None,
        stop_loss: Optional[float] = None,
        position_units: Optional[float] = None,
        margin_used: Optional[float] = None,
        leverage: Optional[int] = None
    ) -> bool:
        """Sends lifecycle status updates (ACTIVE, TARGET HIT, STOPPED, CANCELLED, COMPLETED, TRAILING_STOP)."""
        alert_id = f"{status}_{setup_id}"
        if self.db.is_alert_sent(alert_id):
            logger.info(f"Duplicate lifecycle alert blocked: {alert_id}")
            return False

        message = format_lifecycle_alert(
            coin=coin,
            direction=direction,
            status=status,
            price=price,
            details=details,
            achieved_r=achieved_r,
            pnl=pnl,
            entry=entry,
            stop_loss=stop_loss,
            position_units=position_units,
            margin_used=margin_used,
            leverage=leverage
        )
        buttons = get_trade_inline_keyboard()
        success = await self.send_message(message, reply_markup=buttons)

        self.db.record_alert_sent(alert_id, coin, status)
        return success

    async def send_partial_profit_secured(
        self,
        coin: str,
        direction: str,
        current_price: float,
        secured_pct: int = 40,
        remaining_pct: int = 60,
        realized_pnl_inr: float = 0.0,
        achieved_r: float = 1.0,
        new_stop: Optional[float] = None
    ) -> bool:
        """Dispatches automated partial profit secured notification (+1.0R milestone)."""
        stop_str = f"${new_stop:,.4f}" if new_stop is not None else "Breakeven"
        pnl_str = f"+₹{realized_pnl_inr:,.2f}" if realized_pnl_inr >= 0 else f"-₹{abs(realized_pnl_inr):,.2f}"

        msg = (
            f"💰 *SPIDY CRYPTO — +1.0R MILESTONE: {secured_pct}% PROFIT SECURED!* 🔒\n\n"
            f"• *Market*: `{coin}` ({direction})\n"
            f"• *Execution Price*: `${current_price:,.4f}`\n"
            f"• *Milestone*: `+{achieved_r:.2f}R` reached\n"
            f"• *Profit Banked*: `{secured_pct}%` of position locked in ({pnl_str})\n"
            f"• *Remaining Runner*: `{remaining_pct}%` position active\n"
            f"• *Protective Shield*: Stop Loss moved to `{stop_str}` (Risk-Free)\n\n"
            f"⚡ _The remaining {remaining_pct}% is running risk-free toward Target 2 / higher targets._"
        )
        buttons = get_trade_inline_keyboard()
        return await self.send_message(msg, reply_markup=buttons)


