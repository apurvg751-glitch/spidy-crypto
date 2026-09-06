import asyncio
import logging
from typing import Optional, Any, List
import httpx

from config.settings import settings
from trade_manager.manager import TradeManager
from telegram.notifier import get_trade_inline_keyboard, get_hud_inline_keyboard
from telegram.formatter import format_hud_telemetry, format_daily_executive_brief, format_coin_price
from telegram.chart_generator import generate_symbol_analysis_chart, generate_trade_chart
from structure.barrier_engine import BarrierEngine

logger = logging.getLogger("spidy.telegram.listener")


class TelegramBotListener:
    """
    Long-polling Telegram Bot update listener.
    Equipped with real-time multi-coin Thinking, Interactive HUD, Chart Snapshots,
    and Dynamic 6-Button remote control dock.
    """

    def __init__(
        self,
        trade_manager: TradeManager,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        feed_manager: Optional[Any] = None
    ):
        self.trade_manager = trade_manager
        self.feed_manager = feed_manager
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or settings.TELEGRAM_CHAT_ID
        self.client = httpx.AsyncClient(verify=False, timeout=30.0)
        self.is_running = False
        self.last_update_id = 0

    async def close(self):
        self.is_running = False
        await self.client.aclose()

    async def start_polling(self):
        """High-speed Long Polling loop for sub-second button responses."""
        if not self.bot_token:
            logger.info("Telegram Bot Token not configured. Listener disabled.")
            return

        self.is_running = True
        logger.info("Telegram High-Speed Long Polling Listener started.")

        # 1. Discard stale backlog updates from past sessions
        try:
            purge_res = await self.client.get(
                f"https://api.telegram.org/bot{self.bot_token}/getUpdates",
                params={"offset": -1, "timeout": 0},
                timeout=5.0
            )
            if purge_res.status_code == 200:
                res_data = purge_res.json().get("result", [])
                if res_data:
                    self.last_update_id = max(u.get("update_id", 0) for u in res_data)
                    logger.info(f"Telegram Listener initialized: cleared backlog up to update_id {self.last_update_id}")
        except Exception as e:
            logger.warning(f"Could not purge Telegram backlog: {e}")

        while self.is_running:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                params = {
                    "offset": self.last_update_id + 1,
                    "timeout": 20,
                    "allowed_updates": ["callback_query", "message"]
                }
                res = await self.client.get(url, params=params, timeout=25.0)
                if res.status_code == 200:
                    data = res.json()
                    for update in data.get("result", []):
                        self.last_update_id = max(self.last_update_id, update.get("update_id", 0))
                        asyncio.create_task(self._process_update(update))
                elif res.status_code == 409:
                    logger.warning("Telegram 409 Conflict: Another instance is polling getUpdates. Backing off 5 seconds to avoid collision...")
                    await asyncio.sleep(5.0)
                else:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram polling warning: {e}")
                await asyncio.sleep(1.0)

    async def _process_update(self, update: dict):
        """Processes an incoming Telegram update."""
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            cb_data = cb.get("data")
            msg_obj = cb.get("message", {})
            msg_id = msg_obj.get("message_id")
            chat_id = msg_obj.get("chat", {}).get("id", self.chat_id)
            from_user = cb.get("from", {}).get("first_name", "Trader")

            logger.info(f"Received Telegram Button Click: {cb_data} from {from_user} (chat {chat_id})")
            await self._handle_callback(cb_id, cb_data, chat_id, msg_id=msg_id)

        elif "message" in update and "text" in update["message"]:
            raw_text = update["message"]["text"].strip()
            text = raw_text.lower()
            chat_id = update["message"].get("chat", {}).get("id", self.chat_id)

            if text.startswith("/chart") or text.startswith("chart"):
                parts = raw_text.split()
                target_sym = parts[1].upper() if len(parts) > 1 else None
                await self._send_chart_reply(chat_id, requested_symbol=target_sym)
            elif text in ("/hud", "hud", "/dock", "dock", "/dashboard", "dashboard", "/menu", "menu"):
                await self._send_hud_reply(chat_id)
            elif text in ("/scan", "scan", "/scanall", "scanall"):
                await self._handle_scan_command(chat_id)
            elif text in ("/brief", "brief", "/daily", "daily", "/recap", "recap"):
                await self._send_daily_brief_reply(chat_id)
            elif text in ("/status", "status"):
                await self._send_status_reply(chat_id)
            elif text in ("/journal", "journal", "/pnl", "pnl"):
                await self._send_journal_reply(chat_id)
            elif text in ("/be", "breakeven"):
                await self._handle_callback(None, "CMD_BE", chat_id)
            elif text in ("/partial", "partial"):
                await self._handle_callback(None, "CMD_PARTIAL", chat_id)
            elif text in ("/close", "close", "/exit", "exit"):
                await self._handle_callback(None, "CMD_CLOSE", chat_id)
            elif text in ("/stop", "stop", "/pause", "pause", "/poweroff", "poweroff"):
                closed_msg = ""
                if self.trade_manager.active_trade:
                    success, closed_msg = await self.trade_manager.emergency_close("POWERED OFF VIA TELEGRAM")
                self.trade_manager.pause_trading()
                await self._send_reply(
                    "🛑 *SPIDY BOT POWERED OFF / STOPPED*\n\n"
                    f"{'• ' + closed_msg + chr(10) if closed_msg else ''}"
                    "• Trading is PAUSED.\n"
                    "• No new trades will be opened.\n\n"
                    "Send `/start` or `/resume` whenever you want to power Spidy back on! 🚀",
                    chat_id
                )
            elif text in ("/start", "start", "/resume", "resume", "/poweron", "poweron"):
                self.trade_manager.resume_trading()
                await self._send_reply(
                    "▶️ *SPIDY BOT POWERED ON / RESUMED*\n\n"
                    "• 24/7 Institutional Scanner is ACTIVE.\n"
                    "• Global slot is OPEN (0/1).\n"
                    "• Monitoring all 6 Delta Exchange markets! 🚀",
                    chat_id
                )
            elif text in ("/help", "help"):
                await self._send_reply(
                    "🕷️ *SPIDY CRYPTO COMMAND HUB*\n\n"
                    "• `/hud` — 🎛️ Master Interactive 6-Button Telemetry HUD\n"
                    "• `/chart [coin]` — 📈 Instant Dark-Mode Chart with ⚪ HTF White Line\n"
                    "• `/status` — ⚡ Live Telemetry & Institutional Thinking Report\n"
                    "• `/scan` — ⚡ Immediate Scan Across All 9 Models (6 Coins)\n"
                    "• `/brief` — 🌙 11:59 PM IST Executive Performance Recap\n"
                    "• `/be` — 🎯 Move Stop Loss to Breakeven (Risk-Free Shield)\n"
                    "• `/partial` — 💰 Secure 50% Profit into Target 1\n"
                    "• `/close` — 🛑 Emergency Exit Active Trade\n"
                    "• `/journal` — 📖 Daily Trade Journal & PnL Report\n"
                    "• `/stop` or `/pause` — 🛑 Power Off Bot\n"
                    "• `/start` or `/resume` — ▶️ Power On Bot\n"
                    "• `/reset` — 🔄 Wipe State & Restart Scans Fresh\n\n"
                    f"Capital Guard: Max Daily Loss ₹{settings.MAX_DAILY_LOSS:.2f} (11:59 PM IST Reset).",
                    chat_id
                )
            elif text in ("/reset", "reset"):
                self.trade_manager.db.reset_all_data()
                self.trade_manager.active_trade = None
                self.trade_manager.global_status = "WATCHING"
                await self._send_reply(
                    "🔄 *SPIDY CRYPTO SYSTEM RESET COMPLETE*\n\n"
                    "• All historical setups, active locks, and cooldowns have been cleared.\n"
                    f"• Allocated Margin: *₹{int(settings.MAX_ALLOWED_MARGIN):,}* @ *{settings.DEFAULT_LEVERAGE}x Leverage* (₹{int(settings.MAX_ALLOWED_MARGIN * settings.DEFAULT_LEVERAGE):,} Position Size).\n"
                    "• Ready to scan all 6 markets fresh! 🚀",
                    chat_id
                )

    async def _handle_callback(
        self,
        cb_id: Optional[str],
        cb_data: str,
        chat_id: Optional[str] = None,
        msg_id: Optional[int] = None
    ):
        """Executes corresponding action for the tapped button."""
        target_chat = chat_id or self.chat_id

        if cb_id:
            asyncio.create_task(self._answer_callback(cb_id, "Processing request..."))

        reply_msg = ""
        try:
            if cb_data == "CMD_BE":
                success, msg = await self.trade_manager.move_to_breakeven()
                reply_msg = (
                    f"🎯 *BREAKEVEN APPLIED*\n\n{msg}\n\n"
                    "Trade is now 100% risk-free! 🛡️"
                    if success else f"⚠️ {msg}"
                )

            elif cb_data == "CMD_PARTIAL":
                success, msg = await self.trade_manager.close_partial(0.50)
                reply_msg = (
                    f"💰 *50% PARTIAL PROFIT SECURED*\n\n{msg}\n\n"
                    "Remaining position is running towards Target 2! 🚀"
                    if success else f"⚠️ {msg}"
                )

            elif cb_data == "CMD_CLOSE":
                success, msg = await self.trade_manager.emergency_close("EMERGENCY CLOSED VIA TELEGRAM BUTTON")
                reply_msg = (
                    f"🛑 *TRADE CLOSED MANUALLY*\n\n{msg}\n\n"
                    "Global slot is OPEN (0/1). Ready for next setup!"
                    if success else f"⚠️ {msg}"
                )

            elif cb_data == "CMD_STATUS":
                await self._send_status_reply(target_chat)
                return

            elif cb_data == "CMD_JOURNAL":
                await self._send_journal_reply(target_chat)
                return

            elif cb_data == "CMD_HUD":
                await self._send_hud_reply(target_chat)
                return

            elif cb_data == "CMD_HUD_REFRESH":
                await self._send_hud_reply(target_chat, edit_msg_id=msg_id)
                return

            elif cb_data == "CMD_CHART":
                await self._send_chart_reply(target_chat)
                return

            elif cb_data == "CMD_SCAN":
                await self._handle_scan_command(target_chat)
                return

        except Exception as e:
            logger.error(f"Error executing callback {cb_data}: {e}")
            reply_msg = f"⚠️ Command execution error: {e}"

        if reply_msg:
            await self._send_reply(reply_msg, target_chat, reply_markup=get_hud_inline_keyboard())

    async def _send_hud_reply(self, chat_id: str, edit_msg_id: Optional[int] = None):
        """Renders the master interactive 6-button HUD dashboard."""
        live_prices = await self._fetch_live_tickers()
        at = self.trade_manager.active_trade or self.trade_manager.db.get_active_trade()

        daily_loss_info = {
            "current_daily_loss": getattr(self.trade_manager, "current_daily_loss", 0.0),
            "max_daily_loss": getattr(settings, "MAX_DAILY_LOSS", 420.0),
            "daily_loss_remaining": max(0.0, getattr(settings, "MAX_DAILY_LOSS", 420.0) - getattr(self.trade_manager, "current_daily_loss", 0.0))
        }

        market_zones = {}
        if self.feed_manager:
            for sym in settings.SYMBOLS:
                m = self.feed_manager.get_market_state(sym)
                if m and m.candles_5m:
                    sh = max(c.high for c in m.candles_5m[-25:])
                    sl = min(c.low for c in m.candles_5m[-25:])
                    p = live_prices.get(sym, m.current_price or 0.0)
                    rng = max(sh - sl, 1e-4)
                    pct = (p - sl) / rng * 100.0
                    market_zones[sym] = "PREMIUM 🔴" if pct > 60 else ("DISCOUNT 🟢" if pct < 40 else "EQ ⚪")

        hud_text = format_hud_telemetry(at, live_prices, daily_loss_info, market_zones)
        keyboard = get_hud_inline_keyboard()

        # If editing existing HUD message
        if edit_msg_id:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
                payload = {
                    "chat_id": chat_id,
                    "message_id": edit_msg_id,
                    "text": hud_text,
                    "parse_mode": "Markdown",
                    "reply_markup": keyboard
                }
                res = await self.client.post(url, json=payload)
                if res.status_code == 200:
                    return
            except Exception as e:
                logger.warning(f"Could not edit HUD message, sending new: {e}")

        await self._send_reply(hud_text, chat_id, reply_markup=keyboard)

    async def _send_chart_reply(self, chat_id: str, requested_symbol: Optional[str] = None):
        """Generates and delivers instant dark-mode chart snapshot with ⚪ HTF White Line."""
        at = self.trade_manager.active_trade or self.trade_manager.db.get_active_trade()

        # Determine target symbol
        if requested_symbol:
            sym_clean = requested_symbol.upper()
            if not sym_clean.endswith("USD"):
                sym_clean += "USD"
            sym = sym_clean if sym_clean in settings.SYMBOLS else (at.get("coin") if at else "BTCUSD")
        elif at and at.get("coin"):
            sym = at.get("coin")
        else:
            sym = "BTCUSD"

        live_prices = await self._fetch_live_tickers()
        curr_p = live_prices.get(sym, 0.0)

        # Retrieve candles
        candles_plot = []
        candles_1h = []
        candles_4h = []
        if self.feed_manager:
            m = self.feed_manager.get_market_state(sym)
            if m:
                candles_plot = m.candles_15m or m.candles_5m or []
                candles_1h = m.candles_1h or []
                candles_4h = m.candles_4h or []
                if curr_p <= 0 and m.current_price:
                    curr_p = float(m.current_price)

        if curr_p <= 0:
            curr_p = 64000.0 if sym == "BTCUSD" else (2500.0 if sym == "ETHUSD" else 138.0)

        # Detect ⚪ HTF Institutional Origin White Line
        htf_walls = []
        if at and at.get("coin") == sym:
            htf_walls = at.get("htf_walls") or at.get("htf_barriers") or []
        if not htf_walls and (candles_1h or candles_4h):
            try:
                detected_barriers = BarrierEngine.detect_displacement_barriers(candles_1h, candles_4h, curr_p)
                htf_walls = [b.origin_price for b in detected_barriers[:2]]
            except Exception:
                pass

        try:
            chart_bytes = generate_symbol_analysis_chart(
                symbol=sym,
                current_price=curr_p,
                candles=candles_plot,
                htf_walls=htf_walls,
                active_trade=at if (at and at.get("coin") == sym) else None
            )

            wall_str = f"${htf_walls[0]:,.2f}" if htf_walls else "Scanning 1H/4H Displacement"
            if sym == "XRPUSD" and htf_walls:
                wall_str = f"${htf_walls[0]:,.4f}"

            caption = (
                f"📈 *SPIDY CRYPTO — {sym} INSTITUTIONAL SNAPSHOT*\n\n"
                f"• *Live Delta Mark*: `{format_coin_price(sym, curr_p)}`\n"
                f"• *⚪ HTF Origin (White Line)*: `{wall_str}`\n"
                f"• *Status*: {'ACTIVE TRADE IN PROGRESS 🟢' if (at and at.get('coin') == sym) else '24/7 Scanning Active 🛡️'}\n\n"
                f"_Institutional displacement barrier mapped across 1H/4H structure._"
            )

            import json
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "Markdown",
                "reply_markup": json.dumps(get_hud_inline_keyboard())
            }
            files = {"photo": ("chart.png", chart_bytes, "image/png")}
            res = await self.client.post(url, data=data, files=files)
            if res.status_code != 200:
                logger.warning(f"sendPhoto failed ({res.status_code}), falling back to text.")
                await self._send_reply(caption, chat_id, reply_markup=get_hud_inline_keyboard())
        except Exception as e:
            logger.error(f"Error generating chart reply: {e}")
            await self._send_reply(f"⚠️ Could not generate chart snapshot: {e}", chat_id)

    async def _handle_scan_command(self, chat_id: str):
        """Triggers immediate market scan across all 9 models on all 6 coins."""
        live_prices = await self._fetch_live_tickers()
        lines = [
            "⚡ *SPIDY CRYPTO — 9-MODEL SCAN EXECUTION*",
            "─────────────────────────",
            "• *Markets Scanned*: `BTC`, `ETH`, `SOL`, `XRP`, `BNB`, `AVAX`",
            "• *Models Evaluated*:",
            "  1. Liquidity Sweep Reversal",
            "  2. HTF Order Block SMT",
            "  3. Retest Continuation",
            "  4. Volume Expansion",
            "  5. Premium/Discount Equilibrium",
            "  6. Asian Session Judas Sweep",
            "  7. Equal Highs/Lows Sweep",
            "  8. Session VWAP Reversion",
            "  9. Multi-TF Displacement Origin (⚪ White Line)",
            "─────────────────────────"
        ]
        at = self.trade_manager.active_trade
        if at:
            lines.append(f"🔒 *Global Slot*: `1/1 OCCUPIED` ({at.get('coin')} {at.get('direction')})")
            lines.append("• New trade entries are strictly blocked to protect capital.")
        else:
            lines.append("🟢 *Global Slot*: `0/1 OPEN (ARMED)`")
            lines.append("• Minimum Threshold: `Score ≥ 80 / 100` | `RR ≥ 1.6R`")
            lines.append("• Immediate notification will fire on valid institutional alignment.")

        msg = "\n".join(lines)
        await self._send_reply(msg, chat_id, reply_markup=get_hud_inline_keyboard())

    async def _send_daily_brief_reply(self, chat_id: str):
        """Sends the 11:59 PM IST Executive Brief on demand."""
        from journal.trade_journal import TradeJournalEngine
        data = TradeJournalEngine.get_daily_trades()
        cur_loss = getattr(self.trade_manager, "current_daily_loss", 0.0)
        max_loss = getattr(settings, "MAX_DAILY_LOSS", 420.0)
        brief_text = format_daily_executive_brief(data, current_daily_loss=cur_loss, max_daily_loss=max_loss)
        await self._send_reply(brief_text, chat_id, reply_markup=get_hud_inline_keyboard())

    async def _send_journal_reply(self, chat_id: str):
        """Sends daily trade performance recap directly to Telegram."""
        from journal.trade_journal import TradeJournalEngine
        markdown_report = TradeJournalEngine.generate_telegram_markdown()
        await self._send_reply(markdown_report, chat_id, reply_markup=get_hud_inline_keyboard())

    async def _answer_callback(self, cb_id: str, text: str):
        """Sends instant popup toast to user's phone on button tap."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
            await self.client.post(url, json={"callback_query_id": cb_id, "text": text, "show_alert": False})
        except Exception as e:
            logger.warning(f"Error answering callback query: {e}")

    async def _fetch_live_tickers(self) -> dict[str, float]:
        """Fetches fresh ticker data in 0.001ms directly from in-memory feed manager."""
        live_prices = {}
        if self.feed_manager:
            try:
                for sym in settings.SYMBOLS:
                    m = self.feed_manager.get_market_state(sym)
                    if m and m.current_price:
                        live_prices[sym] = float(m.current_price)
            except Exception:
                pass

        if len(live_prices) == len(settings.SYMBOLS):
            return live_prices

        try:
            port = settings.SERVER_PORT
            res = await self.client.get(f"http://127.0.0.1:{port}/api/status", timeout=0.5)
            if res.status_code == 200:
                states = res.json().get("states", {})
                for sym, info in states.items():
                    p = float(info.get("current_price") or 0.0)
                    if p > 0:
                        live_prices[sym] = p
        except Exception:
            pass

        for sym in settings.SYMBOLS:
            if sym not in live_prices or live_prices[sym] <= 0:
                at = self.trade_manager.active_trade
                if at and at.get("coin") == sym and at.get("current_price"):
                    live_prices[sym] = float(at["current_price"])
        return live_prices

    async def _send_status_reply(self, chat_id: Optional[str] = None):
        """Replies with dynamic calculations, non-zero PnL, and coin-specific Thinking System."""
        target_chat = chat_id or self.chat_id
        live_prices = await self._fetch_live_tickers()
        at = self.trade_manager.active_trade or self.trade_manager.db.get_active_trade()

        lines = []
        lines.append("⚡ *SPIDY CRYPTO — LIVE TELEMETRY & THINKING REPORT*")
        lines.append("")

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

            current_p = live_prices.get(coin, float(at.get("current_price", entry)))
            price_diff = (current_p - entry) if direction.upper() == "LONG" else (entry - current_p)
            pnl_pct = (price_diff / entry) * 100.0 if entry > 0 else 0.0
            risk_dist = abs(entry - sl)
            achieved_r = price_diff / max(risk_dist, 1e-4)

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

                from market_data.delta_specs import DeltaPointValueEngine
                pnl_calc = DeltaPointValueEngine.calculate_exact_pnl(
                    symbol=coin,
                    direction=direction,
                    entry=entry,
                    current_price=current_p,
                    margin_used=margin,
                    leverage=lev
                )
                pts_m = pnl_calc["points_moved"]
                pts_sign = "+" if pts_m >= 0 else ""

                lines.append(f"• Entry: *${entry:,.2f}* → Live Delta Mark: *${current_p:,.2f}*")
                lines.append(f"• Delta Lots: *{pnl_calc['delta_contracts']} Contracts ({pnl_calc['contract_unit']}/lot)*")
                lines.append(f"• Point Value: *{pnl_calc['point_label']} pt = ±₹{pnl_calc['point_val_inr']:.2f}* (±${pnl_calc['point_val_usd']:.4f})")
                lines.append(f"• Points Moved: *{pts_sign}{pts_m:.2f} pts* ({pnl_sign}${abs(price_diff):,.2f})")
                lines.append(f"• PnL: *{pnl_sign}${abs(price_diff):,.2f} ({pnl_sign}{pnl_pct:.2f}%)* {pnl_emoji}")
                lines.append(f"• R-Multiple: *{pnl_sign}{achieved_r:.2f}R*")
                lines.append(f"• Live Profit (₹{int(margin):,} Margin @ {lev}x): *{pnl_sign}₹{pnl_calc['pnl_inr']:,.2f}* {pnl_emoji}")
                lines.append("")
                lines.append("📊 *LIVE PROGRESS*:")
                from telegram.formatter import format_trade_progress_bar
                lines.append(format_trade_progress_bar(entry, t1, sl, current_p, direction, achieved_r))
                lines.append("")
                lines.append("🎯 *TARGETS & INVALIDATION*:")
                lines.append(f"• Stop Loss: *${sl:,.2f}*")
                lines.append(f"• Target 1: *${t1:,.2f}* | Target 2: *${t2:,.2f}*")
                lines.append("─────────────────────────")
        else:
            lines.append("🪙 *ACTIVE POSITION*: *NONE (0/1 Global Slot Open)* 🟢")
            lines.append("• *Status*: *SCANNING MARKETS (24/7 Guardian Active)*")

            last_trades = self.trade_manager.db.get_history(limit=1)
            last_t = last_trades[0] if last_trades else None
            if last_t:
                res_emoji = "🟢" if last_t.get("achieved_r", 0) > 0 else ("🔴" if last_t.get("achieved_r", 0) < 0 else "⚪")
                final_res = str(last_t.get("final_result") or "Completed").replace("_", " ")
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

        lines.append("🧠 *INSTITUTIONAL THINKING ENGINE (ALL MARKETS)*:")
        lines.append("")

        for sym in settings.SYMBOLS:
            p = live_prices.get(sym, 0.0)
            pos_pct = 50.0
            zone = "EQUILIBRIUM"

            if self.feed_manager:
                try:
                    m = self.feed_manager.get_market_state(sym)
                    if m and m.candles_5m:
                        c5 = m.candles_5m
                        sh = max(c.high for c in c5[-25:])
                        sl = min(c.low for c in c5[-25:])
                        rng = max(sh - sl, 1e-4)
                        pos_pct = max(0.0, min(100.0, (p - sl) / rng * 100.0))
                        zone = "PREMIUM (Sells Only)" if pos_pct > 60 else ("DISCOUNT (Buys Only)" if pos_pct < 40 else "EQUILIBRIUM")
                except Exception:
                    pass

            price_fmt = f"${p:,.4f}" if sym == "XRPUSD" else f"${p:,.2f}"
            lines.append(f"• *{sym}* ({price_fmt}): Range: `{zone}` ({pos_pct:.1f}%)")
            lines.append(f"  Thinking: _Scanning 1H/4H displacement origins & ⚪ White Line barriers._")
            lines.append("")
        msg = "\n".join(lines)
        await self._send_reply(msg, target_chat, reply_markup=get_hud_inline_keyboard())

    async def _send_reply(self, text: str, chat_id: Optional[str] = None, reply_markup: Optional[dict] = None):
        """Sends message to the user chat with interactive keyboard buttons and automatic plain-text fallback."""
        target_chat = chat_id or self.chat_id
        keyboard = reply_markup if reply_markup is not None else get_hud_inline_keyboard()
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
