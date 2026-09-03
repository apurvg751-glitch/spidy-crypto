import asyncio
import logging
import time
from typing import Any, Callable, Optional, Union

from config.settings import settings
from storage.database import Database
from telegram.notifier import TelegramNotifier
from strategy.setup_detector import DetectedSetup
from strategy.models.base_model import StrategyCandidate
from risk_engine.position_sizing import PositionSizer
from structure.trailing_engine import TrailingStopEngine
from strategy.reentry_manager import ReentryManager

logger = logging.getLogger("spidy.trade_manager")


class TradeManager:
    """
    Central Trade Manager for SPIDY CRYPTO.
    Enforces the single-active-trade global lock (MAX_ACTIVE_TRADES = 1),
    handles multi-coin setup arbitration across all 6 models,
    tracks trade lifecycle state machine, position sizing (₹250 max margin option),
    MFE/MAE excursions, and persists model-specific performance metrics to SQLite.
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        telegram: Optional[TelegramNotifier] = None,
        on_state_change: Optional[Callable[[dict[str, Any]], None]] = None,
        cooldown_seconds: Optional[int] = None
    ):
        self.db = db or Database()
        self.telegram = telegram or TelegramNotifier(db=self.db)
        self.on_state_change = on_state_change
        self.cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else settings.COOLDOWN_SECONDS
        self.reentry_manager = ReentryManager(db=self.db)

        self._lock = asyncio.Lock()
        self.active_trade: Optional[dict[str, Any]] = None
        self.global_status: str = "WATCHING"

        # Portfolio Safeguard State
        self.current_daily_loss: float = 0.0
        self.consecutive_losses: int = 0
        self.last_trade_close_time: int = 0

        # Restore any active trade from database upon initialization (Crash Recovery)
        self.restore_state_from_db()

    def restore_state_from_db(self):
        """Restores the single active trade from SQLite across application restarts."""
        stored = self.db.get_active_trade()
        if stored:
            self.active_trade = stored
            self.global_status = stored.get("trade_status", "ACTIVE")
            logger.info(f"Restored active trade from DB: {stored['coin']} ({stored['direction']}) in status {self.global_status}")
        else:
            self.active_trade = None
            self.global_status = "WATCHING"
            logger.info("Trade Manager initialized: 0 active trades. Global slot is OPEN.")

    async def process_candidates(
        self,
        candidates: list[Union[DetectedSetup, StrategyCandidate]]
    ) -> Optional[dict[str, Any]]:
        """
        Arbitrates candidate setups from ETH, BTC, SOL across all models.
        Enforces MAX_ACTIVE_TRADES = 1 and selects the strongest setup if multiple trigger.
        """
        if not candidates:
            return None

        async with self._lock:
            # 1. Check if an active trade already exists
            if self.active_trade is not None and self.active_trade.get("trade_status") in ("WAITING", "ACTIVE"):
                active_coin = self.active_trade["coin"]
                active_status = self.active_trade["trade_status"]
                logger.info(f"Global slot occupied by {active_coin} ({active_status}). Rejecting {len(candidates)} candidate(s).")

                for cand in candidates:
                    cand_dict = cand.model_dump()
                    rejection_reason = f"BLOCKED BY ACTIVE TRADE: {active_coin} is currently in {active_status} status."
                    self.db.save_setup(
                        setup_dict=cand_dict,
                        is_selected=False,
                        is_rejected=True,
                        rejection_reason=rejection_reason,
                        trade_status="BLOCKED BY ACTIVE TRADE"
                    )
                return None

            # 2. If multiple candidates trigger concurrently, rank and pick the strongest
            ranked = sorted(
                candidates,
                key=lambda x: (
                    x.setup_score,
                    x.rr,
                    1 if getattr(x, "volume_confirmed", False) or (hasattr(x, "confirmations") and getattr(x.confirmations, "volume_ok", False)) else 0
                ),
                reverse=True
            )

            winner = ranked[0]
            losers = ranked[1:]

            # Persist and reject the weaker candidates with transparent reasoning
            for loser in losers:
                loser_dict = loser.model_dump()
                rejection_reason = (
                    f"Rejected in favor of higher-ranked setup: Selected {winner.coin} "
                    f"(Score: {winner.setup_score}, RR: {winner.rr:.1f}) over {loser.coin} "
                    f"(Score: {loser.setup_score}, RR: {loser.rr:.1f})"
                )
                self.db.save_setup(
                    setup_dict=loser_dict,
                    is_selected=False,
                    is_rejected=True,
                    rejection_reason=rejection_reason,
                    trade_status="BLOCKED BY ACTIVE TRADE"
                )
                logger.info(f"Setup {loser.coin} rejected: {rejection_reason}")

            # 3. Position Sizing & Portfolio Risk Check
            pos_calc = PositionSizer.calculate_position(
                entry=winner.entry,
                stop_loss=winner.stop_loss,
                account_equity=settings.ACCOUNT_EQUITY,
                max_risk_pct=settings.MAX_RISK_PCT,
                max_allowed_margin=settings.MAX_ALLOWED_MARGIN,
                leverage=settings.DEFAULT_LEVERAGE,
                current_daily_loss=self.current_daily_loss,
                consecutive_losses=self.consecutive_losses,
                last_trade_close_time=self.last_trade_close_time,
                cooldown_seconds=self.cooldown_seconds
            )

            if not pos_calc.is_allowed:
                logger.warning(f"Winning setup {winner.coin} rejected by risk engine: {pos_calc.rejection_reason}")
                winner_dict = winner.model_dump()
                self.db.save_setup(
                    setup_dict=winner_dict,
                    is_selected=False,
                    is_rejected=True,
                    rejection_reason=pos_calc.rejection_reason,
                    trade_status="REJECTED_BY_RISK"
                )
                return None

            # 4. Promote the winning setup to WAITING (selected active trade)
            winner_dict = winner.model_dump()
            initial_status = "ACTIVE"
            winner_dict["trade_status"] = initial_status
            winner_dict["activated_timestamp"] = int(time.time())
            winner_dict["position_units"] = pos_calc.units
            winner_dict["margin_used"] = pos_calc.required_margin
            winner_dict["model_id"] = getattr(winner, "model_id", "MODEL_1")
            winner_dict["model_name"] = getattr(winner, "model_name", "Liquidity Sweep Reversal")

            # Save in DB as selected setup
            self.db.save_setup(
                setup_dict=winner_dict,
                is_selected=True,
                is_rejected=False,
                rejection_reason="",
                trade_status=initial_status
            )

            active_record = {
                "setup_id": winner.id,
                "coin": winner.coin,
                "direction": winner.direction,
                "entry": winner.entry,
                "stop_loss": winner.stop_loss,
                "target_1": winner.target_1,
                "target_2": winner.target_2,
                "rr": winner.rr,
                "setup_score": winner.setup_score,
                "trade_status": initial_status,
                "reasons": winner.reasons,
                "activated_timestamp": int(time.time()),
                "model_id": getattr(winner, "model_id", "MODEL_1"),
                "model_name": getattr(winner, "model_name", "Liquidity Sweep Reversal"),
                "confirmations_count": getattr(getattr(winner, "confirmations", None), "passed_count", 5),
                "position_units": pos_calc.units,
                "margin_used": pos_calc.required_margin,
                "peak_favorable_price": winner.entry,
                "peak_adverse_price": winner.entry,
                "generation_id": getattr(winner, "generation_id", None),
                "sweep_timestamp": getattr(winner, "sweep_timestamp", None),
                "bos_timestamp": getattr(winner, "bos_timestamp", None),
                "ob_timestamp": getattr(winner, "ob_timestamp", None),
                "fvg_timestamp": getattr(winner, "fvg_timestamp", None),
                "retest_timestamp": getattr(winner, "retest_timestamp", None)
            }
            self.db.set_active_trade(active_record)

            self.active_trade = active_record
            self.global_status = "ACTIVE"
            logger.info(f"Selected and activated new trade: {winner.coin} {winner.direction} [{active_record['model_name']}] (Score: {winner.setup_score}, Margin: ₹{pos_calc.required_margin})")

            # Dispatch primary Telegram Alert
            await self.telegram.send_trade_detected_alert(winner_dict)

            self._notify_state_change()
            return active_record

    async def update_price(self, symbol: str, current_price: float):
        """Monitors incoming price ticks, updates MFE/MAE excursions, and drives state transitions."""
        async with self._lock:
            if not self.active_trade or self.active_trade.get("coin") != symbol:
                return

            status = self.active_trade.get("trade_status")
            direction = self.active_trade.get("direction")
            entry = self.active_trade["entry"]
            stop = self.active_trade["stop_loss"]
            t1 = self.active_trade["target_1"]
            t2 = self.active_trade["target_2"]
            setup_id = self.active_trade["setup_id"]

            self.active_trade["current_price"] = current_price

            # Track peak favorable and adverse excursion
            if direction == "LONG":
                self.active_trade["peak_favorable_price"] = max(self.active_trade.get("peak_favorable_price", entry), current_price)
                self.active_trade["peak_adverse_price"] = min(self.active_trade.get("peak_adverse_price", entry), current_price)
            else:
                self.active_trade["peak_favorable_price"] = min(self.active_trade.get("peak_favorable_price", entry), current_price)
                self.active_trade["peak_adverse_price"] = max(self.active_trade.get("peak_adverse_price", entry), current_price)

            if status == "WAITING":
                dist_pct = abs(current_price - entry) / max(entry, 1.0)
                if dist_pct <= 0.0035:
                    await self._transition_to("ACTIVE", current_price, f"Price entered {direction} execution zone ({current_price:.2f}).")
                elif direction == "LONG" and current_price <= stop:
                    await self._close_trade("CANCELLED", current_price, "Price hit stop before entry triggered.")
                elif direction == "SHORT" and current_price >= stop:
                    await self._close_trade("CANCELLED", current_price, "Price hit stop before entry triggered.")

            elif status == "ACTIVE":
                risk = abs(entry - self.active_trade.get("original_stop", stop))
                be_threshold = 0.6 if self.active_trade.get("grade") == "B+" else 0.8

                # 1. Dynamic Breakeven & Trailing Stop Engine
                peak_fav = self.active_trade.get("peak_favorable_price", current_price)
                atr = self.active_trade.get("atr", entry * 0.005)
                trail_res = TrailingStopEngine.evaluate_trail(
                    direction=direction,
                    entry=entry,
                    original_stop=self.active_trade.get("original_stop", stop),
                    current_stop=self.active_trade["stop_loss"],
                    current_price=current_price,
                    peak_favorable_price=peak_fav,
                    atr=atr
                )
                if trail_res.stop_moved:
                    old_sl = self.active_trade["stop_loss"]
                    self.active_trade["stop_loss"] = trail_res.new_stop
                    self.active_trade["be_moved"] = True
                    self.db.set_active_trade(self.active_trade)
                    logger.info(f"Trailing Stop ratcheted for {symbol}: {old_sl:.2f} -> {trail_res.new_stop:.2f} [{trail_res.trail_reason}]")
                    await self.telegram.send_trade_lifecycle_update(
                        symbol, direction, "TRAILING_STOP", current_price, setup_id,
                        details=f"Trailing Stop ratcheted: {old_sl:.2f} -> {trail_res.new_stop:.2f} ({trail_res.trail_reason})"
                    )
                    self._notify_state_change()

                # 2. Stop Loss Check
                if direction == "LONG" and current_price <= self.active_trade["stop_loss"]:
                    await self._close_trade("STOPPED", current_price, f"Stop loss hit at {current_price:.2f}")
                    return
                elif direction == "SHORT" and current_price >= self.active_trade["stop_loss"]:
                    await self._close_trade("STOPPED", current_price, f"Stop loss hit at {current_price:.2f}")
                    return

                # 3. Target 2 Hit (Full Target)
                elif direction == "LONG" and current_price >= t2:
                    await self._close_trade("COMPLETED", current_price, f"Target 2 hit at {current_price:.2f} (Full Profit)")
                    return
                elif direction == "SHORT" and current_price <= t2:
                    await self._close_trade("COMPLETED", current_price, f"Target 2 hit at {current_price:.2f} (Full Profit)")
                    return

                # 4. Target 1 Hit (B+ exits immediately, A+ locks Breakeven)
                elif direction == "LONG" and current_price >= t1 and not self.active_trade.get("t1_hit"):
                    self.active_trade["t1_hit"] = True
                    if self.active_trade.get("grade") == "B+":
                        await self._close_trade("COMPLETED", current_price, f"Target 1 hit at {current_price:.2f} (B+ Strict TP Secured)")
                        return
                    else:
                        self.active_trade["stop_loss"] = entry
                        self.db.set_active_trade(self.active_trade)
                        await self.telegram.send_trade_lifecycle_update(
                            symbol, direction, "TARGET HIT", current_price, setup_id,
                            details=f"Target 1 reached at {current_price:.2f}! Stop moved to Breakeven ({entry:.2f})."
                        )
                        self._notify_state_change()

                elif direction == "SHORT" and current_price <= t1 and not self.active_trade.get("t1_hit"):
                    self.active_trade["t1_hit"] = True
                    if self.active_trade.get("grade") == "B+":
                        await self._close_trade("COMPLETED", current_price, f"Target 1 hit at {current_price:.2f} (B+ Strict TP Secured)")
                        return
                    else:
                        self.active_trade["stop_loss"] = entry
                        self.db.set_active_trade(self.active_trade)
                        await self.telegram.send_trade_lifecycle_update(
                            symbol, direction, "TARGET HIT", current_price, setup_id,
                            details=f"Target 1 reached at {current_price:.2f}! Stop moved to Breakeven ({entry:.2f})."
                        )
                        self._notify_state_change()

    async def _transition_to(self, new_status: str, price: float, details: str):
        if not self.active_trade:
            return
        self.active_trade["trade_status"] = new_status
        self.global_status = new_status
        self.db.set_active_trade(self.active_trade)
        self.db.update_setup_status(self.active_trade["setup_id"], new_status)

        logger.info(f"Trade {self.active_trade['coin']} transitioned to {new_status} at price {price:.2f}: {details}")
        await self.telegram.send_trade_lifecycle_update(
            coin=self.active_trade["coin"],
            direction=self.active_trade["direction"],
            status=new_status,
            price=price,
            setup_id=self.active_trade["setup_id"],
            details=details
        )
        self._notify_state_change()

    async def _close_trade(self, terminal_status: str, price: float, details: str, custom_r: Optional[float] = None, custom_pnl: Optional[float] = None):
        if not self.active_trade:
            return
        coin = self.active_trade["coin"]
        direction = self.active_trade["direction"]
        setup_id = self.active_trade["setup_id"]
        entry = float(self.active_trade["entry"])
        stop = float(self.active_trade["stop_loss"])
        risk = abs(entry - stop)
        model_id = self.active_trade.get("model_id", "MODEL_1")
        score = self.active_trade.get("setup_score", 80)
        confirmations = self.active_trade.get("confirmations_count", 5)
        now = int(time.time())

        risk_unit = settings.ACCOUNT_EQUITY * (settings.MAX_RISK_PCT / 100.0)

        # Determine outcome, achieved R, and real Rupee PnL
        if custom_r is not None:
            achieved_r = custom_r
            won = (achieved_r > 0)
            pnl = custom_pnl if custom_pnl is not None else round(achieved_r * risk_unit, 2)
        elif terminal_status == "COMPLETED":
            won = True
            achieved_r = float(self.active_trade.get("rr", 2.0))
            pnl = round(achieved_r * risk_unit, 2)
            self.consecutive_losses = 0
        elif terminal_status == "STOPPED":
            won = False
            achieved_r = -1.0
            pnl = -round(risk_unit, 2)
            self.consecutive_losses += 1
            self.current_daily_loss += risk_unit
        else:
            # CANCELLED or manual exit: calculate exact PnL from exit price
            price_diff = (price - entry) if direction == "LONG" else (entry - price)
            achieved_r = round(price_diff / max(risk, 1e-4), 2)
            won = (achieved_r > 0)
            pnl = round(achieved_r * risk_unit, 2)
            terminal_status = "COMPLETED" if won else ("STOPPED" if achieved_r < 0 else "CANCELLED")

        peak_fav = self.active_trade.get("peak_favorable_price", entry)
        peak_adv = self.active_trade.get("peak_adverse_price", entry)
        mfe = round(abs(peak_fav - entry) / max(risk, 1e-4), 2)
        mae = round(abs(peak_adv - entry) / max(risk, 1e-4), 2)

        # Update historical setup record in DB
        self.db.update_setup_status(
            setup_id=setup_id,
            trade_status=terminal_status,
            final_result=details,
            closing_timestamp=now,
            achieved_r=achieved_r,
            pnl=pnl,
            mfe=mfe,
            mae=mae
        )

        # Update persistent model-specific statistics
        if terminal_status in ("COMPLETED", "STOPPED"):
            self.db.update_model_stats(model_id, won, achieved_r, score, confirmations)

        self.last_trade_close_time = now

        # Professional Re-Entry & Cooldown Registration
        try:
            self.reentry_manager.register_trade_close(
                coin=coin,
                trade_id=setup_id,
                result=terminal_status,
                close_price=price,
                candidate_or_trade=self.active_trade
            )
        except Exception as e:
            logger.error(f"Failed to register trade close in ReentryManager: {e}")

        # Clear active trade from DB and memory -> Global Lock Released!
        self.db.clear_active_trade()
        self.active_trade = None
        self.global_status = "WATCHING"

        logger.info(f"Trade {coin} finished ({terminal_status}) at price {price:.2f}. Achieved R: {achieved_r:.1f}. Global lock RELEASED.")
        await self.telegram.send_trade_lifecycle_update(
            coin=coin,
            direction=direction,
            status=terminal_status,
            price=price,
            setup_id=setup_id,
            details=details
        )
        self._notify_state_change()

    def _notify_state_change(self):
        if self.on_state_change:
            try:
                self.on_state_change(self.get_current_status_summary())
            except Exception as e:
                logger.error(f"Error in state change callback: {e}")

    def get_current_status_summary(self) -> dict[str, Any]:
        reentry_status = {}
        if hasattr(self, "reentry_manager"):
            for s in settings.SYMBOLS:
                reentry_status[s] = self.reentry_manager.get_market_status(s)

        return {
            "global_status": self.global_status,
            "has_active_trade": self.active_trade is not None,
            "active_trade": self.active_trade,
            "max_allowed_trades": settings.MAX_ACTIVE_TRADES,
            "current_daily_loss": self.current_daily_loss,
            "consecutive_losses": self.consecutive_losses,
            "reentry_status": reentry_status
        }

    async def move_to_breakeven(self) -> tuple[bool, str]:
        """Manually moves the active trade's stop loss to entry price."""
        async with self._lock:
            if not self.active_trade:
                return False, "No active trade to move to Breakeven."

            entry = self.active_trade["entry"]
            coin = self.active_trade["coin"]
            self.active_trade["stop_loss"] = entry
            self.active_trade["be_moved"] = True
            self.db.set_active_trade(self.active_trade)
            self._notify_state_change()
            return True, f"Stop Loss moved to Breakeven (${entry:,.2f}) for {coin}!"

    async def close_partial(self, pct: float = 0.5) -> tuple[bool, str]:
        """Manually closes a percentage (e.g. 50%) of the active position."""
        async with self._lock:
            if not self.active_trade:
                return False, "No active trade to take partial profit on."

            coin = self.active_trade["coin"]
            entry = self.active_trade["entry"]
            current_p = self.active_trade.get("peak_favorable_price", entry)
            self.active_trade["partial_closed"] = True
            self.active_trade["margin_used"] = round(self.active_trade.get("margin_used", 250.0) * (1.0 - pct), 2)
            self.db.set_active_trade(self.active_trade)
            self._notify_state_change()
            return True, f"Secured {int(pct*100)}% partial profit on {coin} at ${current_p:,.2f}!"

    async def emergency_close(self, reason: str = "MANUALLY CLOSED VIA TELEGRAM") -> tuple[bool, str]:
        """Instantly closes the active trade and clears the global slot, calculating live PnL."""
        async with self._lock:
            if not self.active_trade:
                return False, "No active trade running."

            coin = self.active_trade["coin"]
            entry = float(self.active_trade["entry"])
            stop = float(self.active_trade["stop_loss"])
            direction = self.active_trade["direction"]
            risk = abs(entry - stop)

            # Fetch live market price right now from Delta Exchange
            close_price = self.active_trade.get("current_price", entry)
            try:
                res = await self.telegram.client.get(f"{settings.DELTA_REST_URL}/v2/tickers/{coin}", timeout=2.0)
                if res.status_code == 200:
                    mark = float(res.json().get("result", {}).get("mark_price", 0.0) or res.json().get("result", {}).get("close", 0.0))
                    if mark > 0:
                        close_price = mark
            except Exception:
                pass

            price_diff = (close_price - entry) if direction == "LONG" else (entry - close_price)
            achieved_r = round(price_diff / max(risk, 1e-4), 2)
            risk_unit = settings.ACCOUNT_EQUITY * (settings.MAX_RISK_PCT / 100.0)
            pnl_inr = round(achieved_r * risk_unit, 2)
            terminal_status = "COMPLETED" if achieved_r > 0 else ("STOPPED" if achieved_r < 0 else "CANCELLED")

            await self._close_trade(terminal_status, close_price, reason, custom_r=achieved_r, custom_pnl=pnl_inr)
            price_fmt = f"${close_price:,.4f}" if coin == "XRPUSD" else f"${close_price:,.2f}"
            return True, f"Closed {coin} at {price_fmt} ({pnl_sign}{achieved_r:+.2f}R | {pnl_sign}₹{pnl_inr:,.2f})!"
