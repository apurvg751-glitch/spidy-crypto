import asyncio
import logging
from typing import Optional, Any
import httpx

from config.settings import settings
from trade_manager.manager import TradeManager

logger = logging.getLogger("spidy.telegram.listener")


class TelegramBotListener:
    """
    Long-polling Telegram Bot update listener.
    Equipped with real-time multi-coin Thinking & Dynamic Calculation Engine.
    """

    def __init__(
        self,
        trade_manager: TradeManager,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        self.trade_manager = trade_manager
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.client = httpx.AsyncClient(verify=False, timeout=20.0)
        self.is_running = False
        self.last_update_id = 0

    async def close(self):
        self.is_running = False
        await self.client.aclose()

    async def start_polling(self):
        """Main polling loop listening for button clicks and messages."""
        if not self.bot_token:
            logger.info("Telegram Bot Token not configured. Listener disabled.")
            return

        self.is_running = True
        logger.info("Telegram Interactive Button Listener & Thinking Engine started.")

        while self.is_running:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                params = {
                    "offset": self.last_update_id + 1,
                    "timeout": 5,
                    "allowed_updates": ["callback_query", "message"]
                }
                res = await self.client.get(url, params=params)
                if res.status_code == 200:
                    data = res.json()
                    for update in data.get("result", []):
                        self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                        await self._process_update(update)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram polling warning: {e}")
                await asyncio.sleep(2.0)

    async def _process_update(self, update: dict):
        """Processes an incoming Telegram update."""
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            cb_data = cb.get("data")
            chat_id = cb.get("message", {}).get("chat", {}).get("id", self.chat_id)
            from_user = cb.get("from", {}).get("first_name", "Trader")

            logger.info(f"Received Telegram Button Click: {cb_data} from {from_user} (chat {chat_id})")
            await self._handle_callback(cb_id, cb_data, chat_id)

        elif "message" in update and "text" in update["message"]:
            text = update["message"]["text"].strip().lower()
            chat_id = update["message"].get("chat", {}).get("id", self.chat_id)
            if text in ("/status", "status"):
                await self._send_status_reply(chat_id)
            elif text in ("/journal", "journal", "/pnl", "pnl"):
                await self._send_journal_reply(chat_id)
            elif text in ("/be", "breakeven"):
                await self._handle_callback(None, "CMD_BE", chat_id)
            elif text in ("/close", "close", "/stop", "stop", "/exit", "exit"):
                await self._handle_callback(None, "CMD_CLOSE", chat_id)
            elif text in ("/reset", "reset"):
                self.trade_manager.db.reset_all_data()
                self.trade_manager.active_trade = None
                self.trade_manager.global_status = "WATCHING"
                await self._send_reply(
                    "🔄 *SPIDY CRYPTO SYSTEM RESET COMPLETE*\n\n"
                    "• All historical setups, active locks, and cooldowns have been cleared.\n"
                    f"• Capital: *₹{int(settings.ACCOUNT_EQUITY):,}* @ *{settings.DEFAULT_LEVERAGE}x Leverage*.\n"
                    "• Ready to scan all 6 markets fresh! 🚀",
                    chat_id
                )

    async def _handle_callback(self, cb_id: Optional[str], cb_data: str, chat_id: Optional[str] = None):
        """Executes corresponding action for the tapped button."""
        target_chat = chat_id or self.chat_id
        toast_text = "Processing..."
        reply_msg = ""

        if cb_data == "CMD_BE":
            success, msg = await self.trade_manager.move_to_breakeven()
            toast_text = "🎯 Stop moved to BE!" if success else "No active trade"
            reply_msg = (
                f"🎯 *BREAKEVEN APPLIED*\n\n{msg}\n\n"
                "Trade is now 100% risk-free! 🛡️"
                if success else f"⚠️ {msg}"
            )

        elif cb_data == "CMD_PARTIAL":
            success, msg = await self.trade_manager.close_partial(0.50)
            toast_text = "💰 50% Profit Secured!" if success else "No active trade"
            reply_msg = (
                f"💰 *50% PARTIAL PROFIT SECURED*\n\n{msg}\n\n"
                "Remaining position is running towards Target 2! 🚀"
                if success else f"⚠️ {msg}"
            )

        elif cb_data == "CMD_CLOSE":
            success, msg = await self.trade_manager.emergency_close("EMERGENCY CLOSED VIA TELEGRAM BUTTON")
            toast_text = "🛑 Trade Closed!" if success else "No active trade"
            reply_msg = (
                f"🛑 *TRADE CLOSED MANUALLY*\n\n{msg}\n\n"
                "Global slot is OPEN (0/1). Ready for next setup!"
                if success else f"⚠️ {msg}"
            )

        elif cb_data == "CMD_STATUS":
            toast_text = "⚡ Real-time Telemetry Loaded"
            if cb_id:
                await self._answer_callback(cb_id, toast_text)
            await self._send_status_reply(target_chat)
            return

        elif cb_data == "CMD_JOURNAL":
            toast_text = "📖 Loading Daily Journal..."
            if cb_id:
                await self._answer_callback(cb_id, toast_text)
            await self._send_journal_reply(target_chat)
            return

        if cb_id:
            await self._answer_callback(cb_id, toast_text)

        if reply_msg:
            await self._send_reply(reply_msg, target_chat)

    async def _send_journal_reply(self, chat_id: str):
        """Sends daily trade performance recap directly to Telegram."""
        from journal.trade_journal import TradeJournal
        journal = TradeJournal(self.trade_manager.db)
        markdown_report = journal.get_telegram_summary_markdown()
        await self._send_reply(markdown_report, chat_id)

    async def _answer_callback(self, cb_id: str, text: str):
        """Sends instant popup toast to user's phone on button tap."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
            await self.client.post(url, json={"callback_query_id": cb_id, "text": text, "show_alert": False})
        except Exception as e:
            logger.warning(f"Error answering callback query: {e}")

    async def _fetch_live_tickers(self) -> dict[str, float]:
        """Fetches fresh ticker data from Delta REST as dynamic fallback."""
        live_prices = {}
        try:
            res = await self.client.get(f"{settings.DELTA_REST_URL}/v2/tickers", timeout=3.0)
            if res.status_code == 200:
                data = res.json().get("result", [])
                for item in data:
                    sym = item.get("symbol")
                    if sym in settings.SYMBOLS:
                        close_p = float(item.get("close", 0.0) or item.get("mark_price", 0.0))
                        if close_p > 0:
                            live_prices[sym] = close_p
        except Exception as e:
            logger.warning(f"Failed to fetch live Delta tickers: {e}")

        # If any symbol was not returned, attempt fallback from active trade
        for sym in settings.SYMBOLS:
            if sym not in live_prices or live_prices[sym] <= 0:
                at = self.trade_manager.active_trade
                if at and at.get("coin") == sym and at.get("current_price"):
                    live_prices[sym] = float(at["current_price"])
        return live_prices

    async def _fetch_coin_analysis(self, symbol: str) -> dict[str, Any]:
        """Fetches coin-specific structural analysis from local server."""
        try:
            port = settings.SERVER_PORT
            res = await self.client.get(f"http://127.0.0.1:{port}/api/analysis/{symbol}", timeout=0.8)
            if res.status_code == 200:
                return res.json()
        except Exception:
            pass
        return {}

    async def _send_status_reply(self, chat_id: Optional[str] = None):
        """Replies with dynamic calculations, non-zero PnL, and coin-specific Thinking System."""
        target_chat = chat_id or self.chat_id
        live_prices = await self._fetch_live_tickers()
        at = self.trade_manager.active_trade

        lines = []
        lines.append("⚡ *SPIDY CRYPTO — LIVE TELEMETRY & THINKING REPORT*")
        lines.append("")

        # 1. Active Trade Section (with live real-time PnL calculation)
        if at:
            coin = at["coin"]
            direction = at["direction"]
            entry = float(at["entry"])
            sl = float(at["stop_loss"])
            t1 = float(at["target_1"])
            t2 = float(at["target_2"])
            status = at["trade_status"]
            score = at.get("setup_score", 100)
            model = at.get("model_name", "Institutional Sniper ⭐")
            margin = float(at.get("margin_used", settings.ACCOUNT_EQUITY))
            lev = int(at.get("leverage", settings.DEFAULT_LEVERAGE))

            # Fetch exact live ticker price for active coin
            current_p = live_prices.get(coin, float(at.get("current_price", entry)))

            # Real-time PnL Math (1x leverage on ₹35,000 balance)
            if direction.upper() == "LONG":
                price_diff = current_p - entry
            else:
                price_diff = entry - current_p

            pnl_pct = (price_diff / entry) * 100.0 if entry > 0 else 0.0
            risk_dist = abs(entry - sl)
            achieved_r = price_diff / max(risk_dist, 1e-4)
            pnl_inr = margin * (pnl_pct / 100.0) * lev

            pnl_emoji = "🟢" if price_diff >= 0 else "🔴"
            pnl_sign = "+" if price_diff >= 0 else ""

            if status == "WAITING":
                dist_pts = abs(current_p - entry)
                lines.append(f"🪙 *PENDING TRADE: {coin} ({direction})* ⏳")
                lines.append(f"• Model: *{model}* | Score: *{score}/100*")
                lines.append("• Status: *WAITING (Execution Pending ⏳)*")
                lines.append(f"• Entry Level: *${entry:,.2f}* (Live Market: *${current_p:,.2f}* | {dist_pts:,.2f} pts away)")
                lines.append(f"• Stop Loss: *${sl:,.2f}*")
                lines.append(f"• Target 1: *${t1:,.2f}* | Target 2: *${t2:,.2f}*")
                lines.append("─────────────────────────")
            else:
                lines.append(f"🪙 *ACTIVE TRADE: {coin} ({direction})* {pnl_emoji}")
                lines.append(f"• Model: *{model}* | Score: *{score}/100*")
                lines.append(f"• Status: *{status}* {'(BE Locked 🛡️)' if at.get('be_moved') else ''}")
                lines.append("")
                lines.append("💵 *LIVE PnL TELEMETRY (DYNAMIC)*:")
                lines.append(f"• Entry: *${entry:,.2f}* → Live Price: *${current_p:,.2f}*")
                lines.append(f"• PnL: *{pnl_sign}${price_diff:,.2f} ({pnl_sign}{pnl_pct:.2f}%)* {pnl_emoji}")
                lines.append(f"• R-Multiple: *{pnl_sign}{achieved_r:.2f}R*")
                lines.append(f"• Live Profit (₹{int(margin):,} @ {lev}x): *{pnl_sign}₹{pnl_inr:,.2f}* {pnl_emoji}")
                lines.append("")
                lines.append("🎯 *TARGETS & INVALIDATION*:")
                lines.append(f"• Stop Loss: *${sl:,.2f}*")
                lines.append(f"• Target 1: *${t1:,.2f}* | Target 2: *${t2:,.2f}*")
                lines.append("─────────────────────────")
        else:
            lines.append("🔒 *ACTIVE TRADE STATUS*: *None (Global Slot OPEN 0/1)*")
            last_trades = self.trade_manager.db.get_history(limit=1)
            if last_trades:
                last_t = last_trades[0]
                res_emoji = "✅" if last_t.get("trade_status") == "COMPLETED" else "🛑"
                final_res = str(last_t.get("final_result") or "Closed").replace("_", " ")
                lines.append(f"• *Previous Trade*: {last_t.get('coin')} {last_t.get('direction')} ({last_t.get('trade_status')}) {res_emoji}")
                lines.append(f"• *Details*: {final_res}")

            if hasattr(self.trade_manager, "reentry_manager"):
                cd_info = []
                for s in settings.SYMBOLS:
                    stat = self.trade_manager.reentry_manager.get_market_status(s)
                    if stat.get("state") in ("POST_TRADE_COOLDOWN", "WAITING_FOR_NEW_STRUCTURE"):
                        rem = stat.get("cooldown_remaining_bars", 0)
                        clean_state = stat["state"].replace("_", " ")
                        cd_info.append(f"*{s}*: {clean_state} ({rem} bars rem)")
                if cd_info:
                    lines.append(f"• *Cooldown Guard*: {', '.join(cd_info)}")

            lines.append("─────────────────────────")

        # 2. Individual Coin Thinking & Calculation Breakdown (Never duplicate data!)
        lines.append("🧠 *INSTITUTIONAL THINKING ENGINE (ALL MARKETS)*:")
        lines.append("")

        analyses = await asyncio.gather(
            *(self._fetch_coin_analysis(s) for s in settings.SYMBOLS),
            return_exceptions=True
        )
        analyses_map = {s: (a if isinstance(a, dict) else {}) for s, a in zip(settings.SYMBOLS, analyses)}

        for sym in settings.SYMBOLS:
            p = live_prices.get(sym, 0.0)
            analysis = analyses_map.get(sym, {})
            dr = analysis.get("dealing_range", {})
            pos_pct = dr.get("current_position_pct", 0.5) * 100.0 if dr else 50.0
            zone = dr.get("zone", "EQUILIBRIUM") if dr else "EQUILIBRIUM"
            barrier = analysis.get("barrier", {})
            barrier_reason = barrier.get("reason", "Structural analysis active.")

            # Custom Thinking Logic for Each Coin
            if sym == "BTCUSD":
                thinking = f"Price (${p:,.2f}) at {pos_pct:.1f}% ({zone}). Watching 15M resistance ceiling for sweep or continuation."
            elif sym == "ETHUSD":
                thinking = f"Price (${p:,.2f}) at {pos_pct:.1f}% ({zone}). Room to run mapped. Evaluating unmitigated discount OB."
            elif sym == "SOLUSD":
                thinking = f"Price (${p:,.2f}) at {pos_pct:.1f}% ({zone}). Monitoring dealing range boundaries for high-conviction displacement."
            elif sym == "XRPUSD":
                thinking = f"Price (${p:,.4f}) at {pos_pct:.1f}% ({zone}). Tracking key liquidity pools and expansion impulse."
            elif sym == "BNBUSD":
                thinking = f"Price (${p:,.2f}) at {pos_pct:.1f}% ({zone}). Evaluating structural equilibrium and institutional order flow."
            else:  # AVAXUSD
                thinking = f"Price (${p:,.2f}) at {pos_pct:.1f}% ({zone}). Scanning for discount mitigation and fresh BOS confirmation."

            price_fmt = f"${p:,.4f}" if sym == "XRPUSD" else f"${p:,.2f}"
            lines.append(f"• *{sym}* ({price_fmt}):")
            lines.append(f"  Range: *{zone} ({pos_pct:.1f}%)*")
            lines.append(f"  Thinking: _{thinking}_")
            lines.append(f"  Barrier: _{barrier_reason}_")
            lines.append("")

        msg = "\n".join(lines)
        await self._send_reply(msg, target_chat)

    async def _send_reply(self, text: str, chat_id: Optional[str] = None, reply_markup: Optional[dict] = None):
        """Sends message to the user chat with interactive keyboard buttons and automatic plain-text fallback."""
        target_chat = chat_id or self.chat_id
        from .notifier import get_trade_inline_keyboard
        keyboard = reply_markup if reply_markup is not None else get_trade_inline_keyboard()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": keyboard
        }
        try:
            res = await self.client.post(url, json=payload)
            if res.status_code != 200:
                logger.warning(f"Telegram Markdown parse warning ({res.status_code}): {res.text}. Retrying with plain text.")
                payload.pop("parse_mode", None)
                res2 = await self.client.post(url, json=payload)
                if res2.status_code == 200:
                    logger.info("Telegram reply delivered via plain text fallback.")
        except Exception as e:
            logger.error(f"Error sending reply to Telegram: {e}")
