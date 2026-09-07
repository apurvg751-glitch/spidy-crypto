import asyncio
import logging
import time
from typing import Any, Callable, Optional, Union, Dict

from config.precision import format_price, round_price
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
    tracks trade lifecycle state machine, position sizing (₹4,200 margin @ 6x leverage -> ₹25,200 position),
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
        self.feed_manager: Optional[Any] = None
        self.active_trade: Optional[dict[str, Any]] = None
        self.global_status: str = "WATCHING"
        self.is_paused: bool = False

        # Live Delta Execution Gateway
        self.delta_execution = None
        if getattr(settings, "ENABLE_LIVE_EXECUTION", False):
            try:
                from market_data.delta_execution import DeltaExecutionClient
                self.delta_execution = DeltaExecutionClient()
            except Exception as e:
                logger.warning(f"Could not initialize DeltaExecutionClient: {e}")

        # Portfolio Safeguard State & IST 11:59 PM Midnight Rollover
        from datetime import datetime, timezone, timedelta
        self.ist_tz = timezone(timedelta(hours=5, minutes=30))
        self.current_daily_date: str = datetime.now(self.ist_tz).strftime("%Y-%m-%d")
        self.current_daily_loss: float = 0.0
        self.consecutive_losses: int = 0
        self.last_trade_close_time: int = 0

        # Restore any active trade and daily loss from database upon initialization (Crash Recovery)
        self.restore_state_from_db()

    def check_daily_loss_reset(self) -> bool:
        """
        Checks if an IST calendar day has rolled over at 11:59 PM IST (23:59 IST).
        If the date has changed, resets current_daily_loss to 0.0 and refreshes the ₹195.00 budget.
        Returns True if a reset was triggered.
        """
        from datetime import datetime
        today_ist = datetime.now(self.ist_tz).strftime("%Y-%m-%d")
        if self.current_daily_date != today_ist:
            old_date = self.current_daily_date
            old_loss = self.current_daily_loss
            self.current_daily_date = today_ist
            self.current_daily_loss = 0.0
            if self.db:
                self.db.set_config("daily_loss_date", today_ist)
                self.db.set_config("daily_loss_amount", "0.0")
            logger.info(
                f"🌅 11:59 PM IST Midnight Rollover: Daily loss reset from ₹{old_loss:.2f} to ₹0.00 "
                f"for new trading day {today_ist}. Full ₹{settings.MAX_DAILY_LOSS:.2f} daily loss budget restored!"
            )
            if self.telegram:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.telegram.send_midnight_rollover_recap(
                        old_loss=old_loss,
                        new_date=today_ist,
                        max_daily_loss=getattr(settings, "MAX_DAILY_LOSS", 201.0),
                        equity=getattr(settings, "ACCOUNT_EQUITY", 4140.0)
                    ))
                except RuntimeError:
                    pass
            return True
        return False

    def restore_state_from_db(self):
        """Restores the single active trade and daily loss from SQLite across application restarts."""
        is_paused_cfg = self.db.get_config("bot_paused", "false").lower() == "true"
        self.is_paused = is_paused_cfg

        # Restore or reset daily loss based on IST 11:59 PM date
        from datetime import datetime
        today_ist = datetime.now(self.ist_tz).strftime("%Y-%m-%d")
        saved_date = self.db.get_config("daily_loss_date", "")
        if saved_date == today_ist:
            self.current_daily_date = today_ist
            try:
                self.current_daily_loss = float(self.db.get_config("daily_loss_amount", "0.0"))
            except (ValueError, TypeError):
                self.current_daily_loss = 0.0
        else:
            self.current_daily_date = today_ist
            self.current_daily_loss = 0.0
            self.db.set_config("daily_loss_date", today_ist)
            self.db.set_config("daily_loss_amount", "0.0")

        stored = self.db.get_active_trade()
        if stored:
            self.active_trade = stored
            self.global_status = "STOPPED" if self.is_paused else stored.get("trade_status", "ACTIVE")
            logger.info(f"Restored active trade from DB: {stored['coin']} ({stored['direction']}) in status {self.global_status}")
        else:
            self.active_trade = None
            self.global_status = "STOPPED" if self.is_paused else "WATCHING"
            logger.info(f"Trade Manager initialized: 0 active trades. Global status is {self.global_status}. Daily loss: ₹{self.current_daily_loss:.2f} (Date: {today_ist} IST).")

    def pause_trading(self) -> str:
        """Pauses the bot so no new trades are entered."""
        self.is_paused = True
        self.global_status = "STOPPED"
        self.db.set_config("bot_paused", "true")
        self._notify_state_change()
        logger.info("Spidy Bot trading PAUSED by user.")
        return "Trading paused. Bot will not enter any new trades."

    def resume_trading(self) -> str:
        """Resumes the bot so it can enter new trades."""
        self.is_paused = False
        self.global_status = "ACTIVE" if self.active_trade else "WATCHING"
        self.db.set_config("bot_paused", "false")
        self._notify_state_change()
        logger.info("Spidy Bot trading RESUMED by user.")
        return "Trading resumed. Bot is actively scanning and eligible to trade."

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

        if self.is_paused:
            logger.info(f"Spidy Bot is STOPPED/PAUSED. Rejecting {len(candidates)} candidate(s).")
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

            # 2a. Bitcoin Mother-Ship Directional Lock
            if getattr(self, "feed_manager", None):
                btc_state = self.feed_manager.get_market_state("BTCUSD")
                btc_candles = btc_state.candles_15m if btc_state else []
                from strategy.btc_anchor import BtcAnchorEngine
                btc_res = BtcAnchorEngine.evaluate_btc_alignment(winner.coin, winner.direction, btc_candles)
                if not btc_res.is_allowed:
                    logger.warning(f"Winning setup {winner.coin} blocked by BTC Mother-Ship: {btc_res.rejection_reason}")
                    winner_dict = winner.model_dump()
                    self.db.save_setup(
                        setup_dict=winner_dict,
                        is_selected=False,
                        is_rejected=True,
                        rejection_reason=btc_res.rejection_reason,
                        trade_status="BLOCKED_BY_BTC_ANCHOR"
                    )
                    return None

            # 2b. Fake Breakout vs. Real Breakout Gate (Bull/Bear Trap Filter)
            if getattr(winner, "model_id", "") in ("MODEL_2", "MODEL_5", "MODEL_10"):
                if getattr(self, "feed_manager", None):
                    m_state = self.feed_manager.get_market_state(winner.coin)
                    c5 = m_state.candles_5m if m_state else []
                    if c5:
                        from structure.breakout_validator import BreakoutValidator
                        bo_res = BreakoutValidator.validate_breakout(
                            candles=c5,
                            breakout_level=winner.entry,
                            direction=winner.direction,
                            atr=getattr(winner, "atr", winner.entry * 0.005)
                        )
                        if bo_res.is_fake_breakout:
                            rejection_msg = f"BLOCKED BY BREAKOUT VALIDATOR: Fake breakout trap detected ({bo_res.trap_type})."
                            logger.warning(f"Setup {winner.coin} blocked: {rejection_msg}")
                            winner_dict = winner.model_dump()
                            self.db.save_setup(
                                setup_dict=winner_dict,
                                is_selected=False,
                                is_rejected=True,
                                rejection_reason=rejection_msg,
                                trade_status="BLOCKED_BY_FAKE_BREAKOUT"
                            )
                            return None

            # 2c. Retest Reference Analysis (Informational only - do NOT override entry for market orders)
            from strategy.retest_snapper import RetestSnapper
            retest_res = RetestSnapper.calculate_optimal_entry(
                symbol=winner.coin,
                direction=winner.direction,
                current_close=winner.entry,
                atr=getattr(winner, "atr", winner.entry * 0.005)
            )
            if retest_res.discount_pips > 0:
                winner.reasons.append(f"Retest Structure: FVG/OB reference at {retest_res.optimal_entry} ({retest_res.entry_type})")

            # 3. Position Sizing & Portfolio Risk Check (with 11:59 PM IST daily rollover check)
            self.check_daily_loss_reset()

            # Dynamic Live Delta Wallet Balance Synchronization
            live_equity = getattr(settings, "ACCOUNT_EQUITY", 4500.0)
            if self.delta_execution:
                try:
                    wb = await self.delta_execution.get_wallet_balances()
                    if wb.get("success"):
                        for asset in wb.get("result", []):
                            if asset.get("asset_symbol") == "USD":
                                bal_inr = float(asset.get("available_balance_inr") or 0.0)
                                if bal_inr > 0:
                                    live_equity = bal_inr
                                else:
                                    bal_usd = float(asset.get("available_balance") or 0.0)
                                    if bal_usd > 0:
                                        live_equity = bal_usd * getattr(settings, "USD_INR_RATE", 87.5)
                                break
                except Exception as e:
                    logger.warning(f"Could not fetch live wallet balance for sizing: {e}")

            pos_calc = PositionSizer.calculate_position(
                entry=winner.entry,
                stop_loss=winner.stop_loss,
                account_equity=live_equity,
                max_risk_pct=settings.MAX_RISK_PCT,
                min_allowed_margin=getattr(settings, "MIN_ALLOWED_MARGIN", 3000.0),
                max_allowed_margin=settings.MAX_ALLOWED_MARGIN,
                leverage=settings.DEFAULT_LEVERAGE,
                current_daily_loss=self.current_daily_loss,
                consecutive_losses=self.consecutive_losses,
                last_trade_close_time=self.last_trade_close_time,
                cooldown_seconds=self.cooldown_seconds,
                max_daily_loss=getattr(settings, "MAX_DAILY_LOSS", 201.0),
                target_rr=getattr(winner, "rr", None),
                grade=getattr(winner, "grade", None),
                coin=winner.coin
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

            from market_data.delta_specs import DeltaPointValueEngine
            pv = DeltaPointValueEngine.calculate_point_value(
                symbol=winner.coin,
                price=winner.entry,
                margin_used=pos_calc.required_margin,
                leverage=pos_calc.leverage
            )

            active_record = {
                "setup_id": winner.id,
                "coin": winner.coin,
                "direction": winner.direction,
                "entry": winner.entry,
                "stop_loss": winner.stop_loss,
                "original_stop": winner.stop_loss,
                "target_1": winner.target_1,
                "target_2": winner.target_2,
                "rr": winner.rr,
                "setup_score": winner.setup_score,
                "grade": getattr(winner, "grade", "A+"),
                "trade_status": initial_status,
                "reasons": winner.reasons,
                "activated_timestamp": int(time.time()),
                "model_id": getattr(winner, "model_id", "MODEL_1"),
                "model_name": getattr(winner, "model_name", "Liquidity Sweep Reversal"),
                "confirmations_count": getattr(getattr(winner, "confirmations", None), "passed_count", 5),
                "position_units": pos_calc.units,
                "margin_used": pos_calc.required_margin,
                "leverage": pos_calc.leverage,
                "peak_favorable_price": winner.entry,
                "peak_adverse_price": winner.entry,
                "point_val_inr": pv.point_value_inr,
                "point_val_usd": pv.point_value_usd,
                "delta_contracts": pv.delta_contracts,
                "contract_unit": pv.contract_unit,
                "point_label": pv.point_label,
                "points_moved": 0.0,
                "pnl_inr": 0.0,
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
                "be_moved": False,
                "t1_hit": False,
                "partial_closed": False,
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

            # Live Delta Exchange Order Execution
            if self.delta_execution and getattr(settings, "ENABLE_LIVE_EXECUTION", False):
                asyncio.create_task(self._submit_live_order(winner, pv))

            # Dispatch primary Telegram Alert (enriched with Delta specs)
            winner_dict["point_val_inr"] = pv.point_value_inr
            winner_dict["point_val_usd"] = pv.point_value_usd
            winner_dict["delta_contracts"] = pv.delta_contracts
            winner_dict["contract_unit"] = pv.contract_unit
            winner_dict["point_label"] = pv.point_label
            await self.telegram.send_trade_detected_alert(winner_dict)

            self._notify_state_change()
            return active_record

    async def _submit_live_order(self, setup: Any, pv: Any):
        """Dispatches live hybrid market entry order and bracket protection to Delta Exchange India."""
        try:
            # Pre-Flight Spread Guard (Max 12 bps = 0.12% spread)
            if hasattr(self.delta_execution, "check_spread"):
                try:
                    res_spread = await self.delta_execution.check_spread(setup.coin, max_spread_bps=12.0)
                    if isinstance(res_spread, (tuple, list)) and len(res_spread) == 3:
                        spread_ok, spread_bps, spread_pct = res_spread
                        if not spread_ok:
                            logger.warning(f"⚠️ [DELTA SPREAD GUARD] Spread on {setup.coin} is wide ({spread_pct:.3f}% / {spread_bps} bps > 12 bps). Waiting 3s for book to normalize...")
                            await asyncio.sleep(3.0)
                except Exception as e:
                    logger.warning(f"Could not perform spread check: {e}")

            side = "buy" if setup.direction.upper() == "LONG" else "sell"
            raw_contracts = getattr(pv, "delta_contracts", 1)
            size = max(1, int(round(raw_contracts)))
            logger.info(f"🚀 [DELTA LIVE HYBRID] Executing {setup.coin} {side.upper()} MARKET entry: size={size} contracts")
            res = await self.delta_execution.place_order(
                symbol=setup.coin,
                side=side,
                order_type="market_order",
                size=size,
                bracket_stop_loss_price=setup.stop_loss,
                bracket_take_profit_price=setup.target_1
            )
            if res.get("success"):
                order_data = res.get("order", {})
                order_id = order_data.get("id")
                fill_price = float(order_data.get("average_fill_price") or order_data.get("limit_price") or setup.entry)
                logger.info(f"✅ [DELTA LIVE HYBRID] Market entry filled on Delta India. Order ID: {order_id}, Fill: {fill_price}")

                # ADOPT EXACT EXCHANGE FILL PRICE: Re-anchor all trade math to reality
                async with self._lock:
                    if self.active_trade and self.active_trade.get("setup_id") == setup.setup_id:
                        old_entry = float(self.active_trade.get("entry", fill_price))
                        old_sl = float(self.active_trade.get("stop_loss", old_entry))
                        risk_dist = abs(old_entry - old_sl)
                        if risk_dist <= 0:
                            risk_dist = fill_price * 0.005
                        dir_str = self.active_trade.get("direction", "LONG").upper()
                        target_rr = float(getattr(setup, "rr", 1.6) or 1.6)
                        if dir_str == "LONG":
                            real_sl = round_price(setup.coin, fill_price - risk_dist)
                            real_tp1 = round_price(setup.coin, fill_price + (risk_dist * target_rr))
                            real_tp2 = round_price(setup.coin, fill_price + (risk_dist * 2.5))
                        else:
                            real_sl = round_price(setup.coin, fill_price + risk_dist)
                            real_tp1 = round_price(setup.coin, fill_price - (risk_dist * target_rr))
                            real_tp2 = round_price(setup.coin, fill_price - (risk_dist * 2.5))

                        self.active_trade["entry"] = fill_price
                        self.active_trade["stop_loss"] = real_sl
                        self.active_trade["original_stop"] = real_sl
                        self.active_trade["target_1"] = real_tp1
                        self.active_trade["target_2"] = real_tp2
                        self.active_trade["peak_favorable_price"] = fill_price
                        self.active_trade["peak_adverse_price"] = fill_price
                        self.db.set_active_trade(self.active_trade)
                        logger.info(f"🎯 [DELTA LIVE] Re-anchored trade to real fill {fill_price}: SL={real_sl}, TP1={real_tp1}, TP2={real_tp2}")
                        self._notify_state_change()

                # Immediately attach/reinforce bracket protection (Stop Loss & Target 1) using calibrated levels
                sl_to_send = self.active_trade.get("stop_loss") if self.active_trade else setup.stop_loss
                tp_to_send = self.active_trade.get("target_1") if self.active_trade else setup.target_1
                await self.delta_execution.place_bracket_order(
                    symbol=setup.coin,
                    stop_loss_price=sl_to_send,
                    take_profit_price=tp_to_send
                )
                logger.info(f"🛡️ [DELTA LIVE HYBRID] Native bracket protection attached on Delta: SL={sl_to_send}, TP1={tp_to_send}")
            else:
                logger.error(f"❌ [DELTA LIVE HYBRID] Market order failed on Delta India: {res.get('error')}")
        except Exception as e:
            logger.error(f"❌ [DELTA LIVE HYBRID] Exception submitting live order: {e}")

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

            # Precise Delta Exchange Point Value & Live PnL Tracking
            from market_data.delta_specs import DeltaPointValueEngine
            pnl_calc = DeltaPointValueEngine.calculate_exact_pnl(
                symbol=symbol,
                direction=direction,
                entry=entry,
                current_price=current_price,
                margin_used=self.active_trade.get("margin_used"),
                leverage=self.active_trade.get("leverage")
            )
            self.active_trade["points_moved"] = pnl_calc["points_moved"]
            self.active_trade["point_val_inr"] = pnl_calc["point_val_inr"]
            self.active_trade["point_val_usd"] = pnl_calc["point_val_usd"]
            self.active_trade["delta_contracts"] = pnl_calc["delta_contracts"]
            self.active_trade["contract_unit"] = pnl_calc["contract_unit"]
            self.active_trade["point_label"] = pnl_calc["point_label"]
            self.active_trade["pnl_inr"] = pnl_calc["pnl_inr"]
            self.active_trade["pnl_usd"] = pnl_calc["pnl_usd"]
            self.active_trade["pnl_pct"] = pnl_calc["pnl_pct"]

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

                candles_5m = None
                if getattr(self, "feed_manager", None):
                    m_state = self.feed_manager.get_market_state(symbol)
                    if m_state and m_state.candles_5m:
                        candles_5m = m_state.candles_5m

                trail_res = TrailingStopEngine.evaluate_trail(
                    direction=direction,
                    entry=entry,
                    original_stop=self.active_trade.get("original_stop", stop),
                    current_stop=self.active_trade["stop_loss"],
                    current_price=current_price,
                    peak_favorable_price=peak_fav,
                    atr=atr,
                    candles_5m=candles_5m,
                    symbol=symbol
                )
                if trail_res.stop_moved:
                    old_sl = self.active_trade["stop_loss"]
                    self.active_trade["stop_loss"] = trail_res.new_stop
                    self.active_trade["be_moved"] = True
                    self.db.set_active_trade(self.active_trade)
                    logger.info(f"Trailing Stop ratcheted for {symbol}: {format_price(symbol, old_sl)} -> {format_price(symbol, trail_res.new_stop)} [{trail_res.trail_reason}]")

                    # Live Delta Exchange Bracket Order Update
                    if self.delta_execution and getattr(settings, "ENABLE_LIVE_EXECUTION", False):
                        runner_tp = self.active_trade.get("target_2") if self.active_trade.get("partial_closed") else self.active_trade.get("target_1")
                        asyncio.create_task(self.delta_execution.place_bracket_order(
                            symbol=symbol,
                            stop_loss_price=trail_res.new_stop,
                            take_profit_price=runner_tp
                        ))

                    await self.telegram.send_trade_lifecycle_update(
                        symbol, direction, "TRAILING_STOP", current_price, setup_id,
                        details=f"Trailing Stop ratcheted: {format_price(symbol, old_sl)} -> {format_price(symbol, trail_res.new_stop)} ({trail_res.trail_reason})"
                    )
                    self._notify_state_change()

                # 2. Automated +1.0R Milestone Rule: Lock 50% Profit, 50% Runner Safe
                if risk > 0 and not self.active_trade.get("partial_closed"):
                    current_r = ((current_price - entry) / risk) if direction == "LONG" else ((entry - current_price) / risk)
                    if current_r >= 1.0:
                        await self._execute_partial(pct=0.50, current_price=current_price, achieved_r=current_r)

                # 2b. 35-Minute Time Stagnation Advisory Alert (Dead Trade Filter)
                now_ts = int(time.time())
                act_ts = int(self.active_trade.get("activated_timestamp") or now_ts)
                elapsed_seconds = now_ts - act_ts
                current_r = ((current_price - entry) / risk) if (direction == "LONG" and risk > 0) else (((entry - current_price) / risk) if risk > 0 else 0.0)

                # Advisory alert at 35 mins (7 closed 5m candles) if trade has not made directional progress
                if elapsed_seconds >= 2100 and not self.active_trade.get("stagnation_alert_sent") and not self.active_trade.get("partial_closed"):
                    if current_r < 0.50:
                        self.active_trade["stagnation_alert_sent"] = True
                        self.db.set_active_trade(self.active_trade)
                        duration_mins = int(elapsed_seconds / 60)
                        logger.info(f"35-Minute Stagnation Advisory triggered for {symbol}: held {duration_mins}m, current R={current_r:.2f}")
                        if self.telegram:
                            asyncio.create_task(self.telegram.send_stagnation_alert(
                                symbol=symbol,
                                direction=direction,
                                duration_mins=duration_mins,
                                current_r=round(current_r, 2),
                                current_price=current_price
                            ))

                # Optional Hard Velocity & Stagnation Stop Engine (Guarded by ENABLE_TIME_BASED_STAGNATION)
                if getattr(settings, "ENABLE_TIME_BASED_STAGNATION", False):
                    # If trade held > 60 mins without hitting +0.5R, ratchet Stop Loss to Breakeven
                    if elapsed_seconds >= 3600 and current_r < 0.50 and not self.active_trade.get("be_moved"):
                        fee_buf = 0.02 * risk if risk > 0 else 0.0
                        be_level = round_price(symbol, entry + fee_buf if direction == "LONG" else entry - fee_buf)
                        if (direction == "LONG" and self.active_trade["stop_loss"] < be_level) or (direction == "SHORT" and self.active_trade["stop_loss"] > be_level):
                            old_sl = self.active_trade["stop_loss"]
                            self.active_trade["stop_loss"] = be_level
                            self.active_trade["be_moved"] = True
                            self.db.set_active_trade(self.active_trade)
                            logger.info(f"60-Min Stagnation Guard applied for {symbol}: {old_sl} -> {be_level}")
                            await self.telegram.send_trade_lifecycle_update(
                                symbol, direction, "STAGNATION_BE", current_price, setup_id,
                                details=f"60-Min Velocity Guard: Sideways consolidation detected. Stop Loss locked at Breakeven ({format_price(symbol, be_level)})."
                            )
                            self._notify_state_change()

                    # If trade held > 90 mins and still stagnant within +/- 0.25R, scratch at market
                    if elapsed_seconds >= 5400 and (-0.25 <= current_r <= 0.25):
                        logger.info(f"90-Min Stagnation Scratch Exit for {symbol} at {current_price} ({current_r:.2f}R)")
                        await self._close_trade("COMPLETED" if current_r >= 0 else "STOPPED", current_price, f"90-Min Stagnation Scratch Exit ({current_r:.2f}R)")
                        return

                # 3. Stop Loss Check (tested on pullbacks, not on the exact tick that ratcheted stop)
                if not trail_res.stop_moved:
                    if direction == "LONG" and current_price <= self.active_trade["stop_loss"]:
                        orig_stop = float(self.active_trade.get("original_stop", self.active_trade["stop_loss"]))
                        is_trailing = self.active_trade.get("be_moved") or (self.active_trade["stop_loss"] > orig_stop)
                        if is_trailing:
                            reason = f"Trailing Stop Loss Hit at {format_price(symbol, current_price)} (Profit Secured)"
                            await self._close_trade("COMPLETED", current_price, reason)
                        else:
                            reason = f"Original Stop Loss Hit at {format_price(symbol, current_price)} (Risk Protection)"
                            await self._close_trade("STOPPED", current_price, reason)
                        return
                    elif direction == "SHORT" and current_price >= self.active_trade["stop_loss"]:
                        orig_stop = float(self.active_trade.get("original_stop", self.active_trade["stop_loss"]))
                        is_trailing = self.active_trade.get("be_moved") or (self.active_trade["stop_loss"] < orig_stop)
                        if is_trailing:
                            reason = f"Trailing Stop Loss Hit at {format_price(symbol, current_price)} (Profit Secured)"
                            await self._close_trade("COMPLETED", current_price, reason)
                        else:
                            reason = f"Original Stop Loss Hit at {format_price(symbol, current_price)} (Risk Protection)"
                            await self._close_trade("STOPPED", current_price, reason)
                        return

                # 3. Target 2 Hit (Full Target)
                if direction == "LONG" and current_price >= t2:
                    await self._close_trade("COMPLETED", current_price, f"Target 2 hit at {format_price(symbol, current_price)} (Full Profit)")
                    return
                elif direction == "SHORT" and current_price <= t2:
                    await self._close_trade("COMPLETED", current_price, f"Target 2 hit at {format_price(symbol, current_price)} (Full Profit)")
                    return

                # 4. Target 1 Hit (Bank 50% Profit, 50% Runner Safe)
                elif direction == "LONG" and current_price >= t1 and not self.active_trade.get("t1_hit"):
                    self.active_trade["t1_hit"] = True
                    if not self.active_trade.get("partial_closed"):
                        await self._execute_partial(pct=0.50, current_price=current_price, achieved_r=1.0)
                    elif self.active_trade["stop_loss"] < entry:
                        self.active_trade["stop_loss"] = entry
                        self.active_trade["be_moved"] = True
                        self.db.set_active_trade(self.active_trade)
                        await self.telegram.send_trade_lifecycle_update(
                            symbol, direction, "TARGET HIT", current_price, setup_id,
                            details=f"Target 1 reached at {format_price(symbol, current_price)}! Stop moved to Breakeven ({format_price(symbol, entry)})."
                        )
                        self._notify_state_change()

                elif direction == "SHORT" and current_price <= t1 and not self.active_trade.get("t1_hit"):
                    self.active_trade["t1_hit"] = True
                    if not self.active_trade.get("partial_closed"):
                        await self._execute_partial(pct=0.50, current_price=current_price, achieved_r=1.0)
                    elif self.active_trade["stop_loss"] > entry:
                        self.active_trade["stop_loss"] = entry
                        self.active_trade["be_moved"] = True
                        self.db.set_active_trade(self.active_trade)
                        await self.telegram.send_trade_lifecycle_update(
                            symbol, direction, "TARGET HIT", current_price, setup_id,
                            details=f"Target 1 reached at {format_price(symbol, current_price)}! Stop moved to Breakeven ({format_price(symbol, entry)})."
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
            details=details,
            entry=self.active_trade.get("entry"),
            stop_loss=self.active_trade.get("stop_loss"),
            position_units=self.active_trade.get("position_units"),
            margin_used=self.active_trade.get("margin_used"),
            leverage=self.active_trade.get("leverage"),
            target_1=self.active_trade.get("target_1"),
            target_2=self.active_trade.get("target_2"),
            htf_walls=self.active_trade.get("htf_walls") or self.active_trade.get("htf_barriers")
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

        original_stop = float(self.active_trade.get("original_stop", stop))
        risk_dist = abs(entry - original_stop)
        price_diff = (price - entry) if direction.upper() == "LONG" else (entry - price)
        margin_used = float(self.active_trade.get("margin_used") or settings.MAX_ALLOWED_MARGIN)
        leverage = int(self.active_trade.get("leverage") or settings.DEFAULT_LEVERAGE)
        position_units = float(self.active_trade.get("position_units") or 0.0)
        pct_move = (price_diff / entry) if entry > 0 else 0.0
        pct_risk = (risk_dist / entry) if entry > 0 else 0.0

        actual_risk_inr = margin_used * leverage * pct_risk
        exact_pnl_inr = margin_used * leverage * pct_move
        realized_partial = float(self.active_trade.get("realized_partial_pnl") or 0.0)
        exact_pnl_inr += realized_partial

        # Dynamic Variable Realized PnL & R-Multiple Calculation
        if custom_r is not None:
            achieved_r = round(custom_r, 2)
            won = (achieved_r > 0.05)
            pnl = round(custom_pnl if custom_pnl is not None else exact_pnl_inr, 2)
        elif terminal_status == "COMPLETED":
            won = True
            raw_r = price_diff / max(risk_dist, 1e-4)
            achieved_r = round(raw_r if raw_r > 0 else float(self.active_trade.get("rr", 2.0)), 2)
            pnl = round(exact_pnl_inr, 2)
            self.consecutive_losses = 0
        elif terminal_status == "STOPPED":
            achieved_r = round(price_diff / max(risk_dist, 1e-4), 2)
            pnl = round(exact_pnl_inr, 2)
            won = (achieved_r > 0.05)
            is_breakeven = (-0.08 <= achieved_r <= 0.08)

            if won:
                # Stopped out in profit via trailing stop ratchet!
                terminal_status = "COMPLETED"
                self.consecutive_losses = 0
            elif is_breakeven:
                # Protected Break-Even exit: zero/negligible loss, do not count as full loss streak
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
                self.check_daily_loss_reset()
                self.current_daily_loss += abs(pnl)
                if self.db:
                    self.db.set_config("daily_loss_date", self.current_daily_date)
                    self.db.set_config("daily_loss_amount", str(round(self.current_daily_loss, 2)))
        else:
            # CANCELLED or manual emergency exit: exact dynamic calculation
            achieved_r = round(price_diff / max(risk_dist, 1e-4), 2)
            pnl = round(exact_pnl_inr, 2)
            won = (achieved_r > 0.05)
            if achieved_r > 0.05:
                terminal_status = "COMPLETED"
            elif achieved_r < -0.08:
                terminal_status = "STOPPED"
                self.consecutive_losses += 1
                self.check_daily_loss_reset()
                self.current_daily_loss += abs(pnl)
                if self.db:
                    self.db.set_config("daily_loss_date", self.current_daily_date)
                    self.db.set_config("daily_loss_amount", str(round(self.current_daily_loss, 2)))
            else:
                terminal_status = "CANCELLED"

        peak_fav = self.active_trade.get("peak_favorable_price", entry)
        peak_adv = self.active_trade.get("peak_adverse_price", entry)
        mfe = round(abs(peak_fav - entry) / max(risk_dist, 1e-4), 2)
        mae = round(abs(peak_adv - entry) / max(risk_dist, 1e-4), 2)

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

        # Live Delta Execution Cleanup (Cancel orders & close position)
        if self.delta_execution and getattr(settings, "ENABLE_LIVE_EXECUTION", False):
            try:
                contracts = max(1, int(self.active_trade.get("delta_contracts") or 1))
                exit_side = "sell" if direction.upper() == "LONG" else "buy"
                asyncio.create_task(self.delta_execution.cancel_all_orders(symbol=coin))
                asyncio.create_task(self.delta_execution.place_order(
                    symbol=coin,
                    side=exit_side,
                    order_type="market_order",
                    size=contracts,
                    reduce_only=True
                ))
            except Exception as e:
                logger.error(f"Error executing live Delta cleanup on trade close: {e}")

        # Clear active trade from DB and memory -> Global Lock Released!
        self.db.clear_active_trade()
        self.active_trade = None
        self.global_status = "WATCHING"

        # 1-Trade Auto-Halt Guard: Automatically pause Spidy after this trade completes
        if getattr(settings, "SINGLE_TRADE_MODE", True):
            self.is_paused = True
            self.global_status = "STOPPED"
            logger.info("🛑 [SINGLE TRADE MODE] Auto-paused Spidy after trade finished.")

        logger.info(f"Trade {coin} finished ({terminal_status}) at price {price:.2f}. Units: {position_units:.4g}, Margin: ₹{margin_used:.2f}, Achieved R: {achieved_r:.2f}, PnL: ₹{pnl:.2f}. Global lock RELEASED.")
        await self.telegram.send_trade_lifecycle_update(
            coin=coin,
            direction=direction,
            status=terminal_status,
            price=price,
            setup_id=setup_id,
            details=details,
            achieved_r=achieved_r,
            pnl=pnl,
            entry=entry,
            stop_loss=original_stop,
            position_units=position_units,
            margin_used=margin_used,
            leverage=leverage
        )
        self._notify_state_change()

    def _notify_state_change(self):
        if self.on_state_change:
            try:
                self.on_state_change(self.get_current_status_summary())
            except Exception as e:
                logger.error(f"Error in state change callback: {e}")

    def get_current_status_summary(self) -> dict[str, Any]:
        self.check_daily_loss_reset()
        reentry_status = {}
        if hasattr(self, "reentry_manager"):
            for s in settings.SYMBOLS:
                reentry_status[s] = self.reentry_manager.get_market_status(s)

        max_dl = getattr(settings, "MAX_DAILY_LOSS", 201.0)
        daily_loss_rem = max(0.0, max_dl - self.current_daily_loss)

        return {
            "global_status": self.global_status,
            "is_paused": self.is_paused,
            "has_active_trade": self.active_trade is not None,
            "active_trade": self.active_trade,
            "max_allowed_trades": settings.MAX_ACTIVE_TRADES,
            "current_daily_loss": round(self.current_daily_loss, 2),
            "max_daily_loss": max_dl,
            "daily_loss_remaining": round(daily_loss_rem, 2),
            "current_daily_date": getattr(self, "current_daily_date", ""),
            "consecutive_losses": self.consecutive_losses,
            "reentry_status": reentry_status
        }

    async def move_to_breakeven(self, protect_fees: bool = False) -> tuple[bool, str]:
        """Manually moves the active trade's stop loss to entry price (or fee-protected level if protect_fees=True)."""
        async with self._lock:
            if not self.active_trade:
                return False, "No active trade to move to Breakeven."

            entry = float(self.active_trade["entry"])
            coin = self.active_trade["coin"]
            direction = self.active_trade["direction"]
            orig_stop = float(self.active_trade.get("original_stop", self.active_trade["stop_loss"]))
            risk = abs(entry - orig_stop)

            if protect_fees:
                fee_buf = max(0.05 * risk, entry * 0.0008) if risk > 0 else (entry * 0.0008)
                be_level = round_price(coin, entry + fee_buf if direction == "LONG" else entry - fee_buf)
            else:
                be_level = entry

            self.active_trade["stop_loss"] = be_level
            self.active_trade["be_moved"] = True
            self.db.set_active_trade(self.active_trade)

            # Live Delta Breakeven Stop Adjustment
            if self.delta_execution and getattr(settings, "ENABLE_LIVE_EXECUTION", False):
                try:
                    runner_tp = self.active_trade.get("target_2") if self.active_trade.get("partial_closed") else self.active_trade.get("target_1")
                    asyncio.create_task(self.delta_execution.place_bracket_order(
                        symbol=coin,
                        stop_loss_price=be_level,
                        take_profit_price=runner_tp
                    ))
                except Exception as e:
                    logger.error(f"Error adjusting Delta bracket SL to breakeven: {e}")

            self._notify_state_change()
            return True, f"Stop Loss moved to Fee-Protected Breakeven (${be_level:,.4f}) for {coin}!"

    async def sync_live_bracket(self) -> Dict[str, Any]:
        """Synchronizes live bracket order (SL & TP) on Delta Exchange for the current active trade."""
        if not self.active_trade or not self.delta_execution:
            return {"success": False, "error": "No active trade or delta execution client"}
        coin = self.active_trade.get("coin")
        sl = self.active_trade.get("stop_loss")
        tp = self.active_trade.get("target_2") if self.active_trade.get("partial_closed") else self.active_trade.get("target_1")
        logger.info(f"🛡️ [DELTA SYNC] Syncing live bracket for {coin}: SL={sl}, TP={tp}")
        res = await self.delta_execution.place_bracket_order(
            symbol=coin,
            stop_loss_price=sl,
            take_profit_price=tp
        )
        return res

    async def reconcile_with_delta_positions(self) -> Dict[str, Any]:
        """
        Institutional Position Reconciler:
        Queries Delta Exchange India for open positions.
        If an open position exists on the exchange, ensures Spidy tracks it and has bracket orders active.
        """
        if not self.delta_execution or not getattr(settings, "ENABLE_LIVE_EXECUTION", False):
            return {"status": "skipped", "message": "Live execution disabled"}

        try:
            positions = await self.delta_execution.get_positions()
            active_pos = [p for p in positions if float(p.get("size", 0)) != 0]
            if not active_pos:
                return {"status": "clean", "message": "No active open positions on Delta"}

            for pos in active_pos:
                symbol = pos.get("product_symbol") or next((k for k, v in self.delta_execution.product_ids.items() if v == pos.get("product_id")), None)
                size = float(pos.get("size", 0))
                entry_price = float(pos.get("entry_price") or 0)
                if not symbol or size == 0 or entry_price <= 0:
                    continue

                direction = "LONG" if size > 0 else "SHORT"
                # If Spidy does not have an active trade, adopt it
                if not self.active_trade:
                    logger.info(f"🔄 [DELTA RECONCILE] Adopting active position on Delta India: {symbol} {direction} size={size} entry={entry_price}")
                    sl_dist = entry_price * 0.007
                    sl_price = round(entry_price - sl_dist, 4) if direction == "LONG" else round(entry_price + sl_dist, 4)
                    tp1_price = round(entry_price + (sl_dist * 1.6), 4) if direction == "LONG" else round(entry_price - (sl_dist * 1.6), 4)
                    tp2_price = round(entry_price + (sl_dist * 2.5), 4) if direction == "LONG" else round(entry_price - (sl_dist * 2.5), 4)

                    record = {
                        "setup_id": f"{symbol}_RECONCILED_{int(time.time())}",
                        "coin": symbol,
                        "direction": direction,
                        "entry": entry_price,
                        "stop_loss": sl_price,
                        "original_stop": sl_price,
                        "target_1": tp1_price,
                        "target_2": tp2_price,
                        "rr": 2.0,
                        "setup_score": 90,
                        "grade": "B+",
                        "trade_status": "ACTIVE",
                        "activated_timestamp": int(time.time()),
                        "model_id": "RECONCILED",
                        "model_name": "Delta Live Position",
                        "margin_used": 3150.0,
                        "leverage": 6,
                        "delta_contracts": abs(size),
                        "current_price": entry_price,
                        "reasons": ["Adopted live position from Delta Exchange India during reconciliation"]
                    }
                    self.active_trade = record
                    self.db.set_active_trade(record)

                # Ensure bracket protection is active on Delta Exchange
                bracket_res = await self.sync_live_bracket()
                self._notify_state_change()
                return {"status": "reconciled", "symbol": symbol, "bracket_res": bracket_res, "active_trade": self.active_trade}

            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Error during Delta position reconciliation: {e}")
            return {"status": "error", "error": str(e)}

    async def _execute_partial(
        self,
        pct: float = 0.50,
        current_price: Optional[float] = None,
        achieved_r: Optional[float] = None
    ) -> tuple[bool, str]:
        """
        Internal partial execution method (called by automated +1.0R milestone or manual trigger).
        Banks specified percentage (e.g. 50%) in realized profit, reduces margin to remaining runner (50%),
        ensures Stop Loss is locked at Breakeven + fee buffer (+0.05R), and notifies via Telegram.
        """
        if not self.active_trade:
            return False, "No active trade to take partial profit on."
        if self.active_trade.get("partial_closed"):
            return False, "Partial profit already secured on this trade."

        coin = self.active_trade["coin"]
        direction = self.active_trade["direction"]
        entry = float(self.active_trade["entry"])
        stop = float(self.active_trade["stop_loss"])
        orig_stop = float(self.active_trade.get("original_stop", stop))
        risk = abs(entry - orig_stop)
        current_p = current_price if current_price is not None else float(self.active_trade.get("current_price") or self.active_trade.get("peak_favorable_price") or entry)

        if achieved_r is None:
            achieved_r = ((current_p - entry) / risk) if (direction == "LONG" and risk > 0) else (((entry - current_p) / risk) if risk > 0 else 1.0)
        achieved_r = round(achieved_r, 2)

        # 1. Update partial state
        self.active_trade["partial_closed"] = True
        self.active_trade["partial_pct"] = pct
        self.active_trade["partial_price"] = current_p
        self.active_trade["partial_r"] = achieved_r

        orig_margin = float(self.active_trade.get("margin_used") or settings.MAX_ALLOWED_MARGIN)
        leverage = int(self.active_trade.get("leverage") or settings.DEFAULT_LEVERAGE)
        closed_margin = orig_margin * pct
        remaining_margin = round(orig_margin * (1.0 - pct), 2)
        self.active_trade["margin_used"] = remaining_margin

        pct_move = ((current_p - entry) / entry) if (direction == "LONG" and entry > 0) else (((entry - current_p) / entry) if entry > 0 else 0.0)
        realized_pnl_inr = round(closed_margin * leverage * pct_move, 2)
        self.active_trade["realized_partial_pnl"] = realized_pnl_inr

        # 2. Ensure Stop Loss is moved to at least Breakeven + fee buffer (+0.08% / +0.05R)
        fee_buf = max(0.05 * risk, entry * 0.0008) if risk > 0 else (entry * 0.0008)
        if direction == "LONG":
            be_sl = round_price(coin, entry + fee_buf)
            if self.active_trade["stop_loss"] < be_sl:
                self.active_trade["stop_loss"] = be_sl
                self.active_trade["be_moved"] = True
        else:
            be_sl = round_price(coin, entry - fee_buf)
            if self.active_trade["stop_loss"] > be_sl:
                self.active_trade["stop_loss"] = be_sl
                self.active_trade["be_moved"] = True

        self.db.set_active_trade(self.active_trade)

        # 3. Live Delta Partial Execution & Bracket Update (50% Bank & 50% Runner)
        if self.delta_execution and getattr(settings, "ENABLE_LIVE_EXECUTION", False):
            try:
                total_contracts = max(1, int(round(self.active_trade.get("delta_contracts") or 1)))
                closed_contracts = int(round(total_contracts * pct))
                if closed_contracts == 0 and total_contracts > 1:
                    closed_contracts = 1

                exit_side = "sell" if direction.upper() == "LONG" else "buy"
                if closed_contracts > 0 and total_contracts > 1:
                    remaining_contracts = total_contracts - closed_contracts
                    self.active_trade["delta_contracts"] = remaining_contracts
                    logger.info(f"🚀 [DELTA LIVE] Banking 50% partial: closing {closed_contracts} contracts of {coin} (remaining runner: {remaining_contracts})")
                    asyncio.create_task(self.delta_execution.place_order(
                        symbol=coin,
                        side=exit_side,
                        order_type="market_order",
                        size=closed_contracts,
                        reduce_only=True
                    ))

                runner_tp = self.active_trade.get("target_2")
                logger.info(f"🛡️ [DELTA LIVE] Advancing bracket to Breakeven SL ({self.active_trade['stop_loss']}) & Runner TP2 ({runner_tp})")
                asyncio.create_task(self.delta_execution.place_bracket_order(
                    symbol=coin,
                    stop_loss_price=self.active_trade["stop_loss"],
                    take_profit_price=runner_tp
                ))
            except Exception as e:
                logger.error(f"❌ [DELTA LIVE] Error executing live partial on Delta India: {e}")

        logger.info(
            f"Partial Profit Executed for {coin}: {int(pct*100)}% secured at {format_price(coin, current_p)} "
            f"(+{achieved_r:.2f}R | +₹{realized_pnl_inr:,.2f}). Remaining margin: ₹{remaining_margin:,.2f}"
        )

        remaining_pct = int((1.0 - pct) * 100)
        secured_pct = int(pct * 100)
        try:
            await self.telegram.send_partial_profit_secured(
                coin=coin,
                direction=direction,
                current_price=current_p,
                secured_pct=secured_pct,
                remaining_pct=remaining_pct,
                realized_pnl_inr=realized_pnl_inr,
                achieved_r=achieved_r,
                new_stop=self.active_trade["stop_loss"]
            )
        except Exception as e:
            logger.error(f"Failed to dispatch partial profit Telegram alert: {e}")

        self._notify_state_change()
        return True, f"Secured {secured_pct}% partial profit on {coin} at {format_price(coin, current_p)}!"

    async def close_partial(self, pct: float = 0.50) -> tuple[bool, str]:
        """Manually closes a percentage (e.g. 50%) of the active position."""
        async with self._lock:
            return await self._execute_partial(pct=pct)


    async def emergency_close(self, reason: str = "Manually Closed via Telegram Button") -> tuple[bool, str]:
        """Instantly closes the active trade and clears the global slot, calculating live PnL."""
        async with self._lock:
            if not self.active_trade:
                return False, "No active trade running."

            coin = self.active_trade["coin"]
            entry = float(self.active_trade["entry"])
            stop = float(self.active_trade["stop_loss"])
            original_stop = float(self.active_trade.get("original_stop", stop))
            direction = self.active_trade["direction"]
            risk = abs(entry - original_stop)

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
            margin_used = float(self.active_trade.get("margin_used") or settings.MAX_ALLOWED_MARGIN)
            leverage = int(self.active_trade.get("leverage") or settings.DEFAULT_LEVERAGE)
            pct_move = (price_diff / entry) if entry > 0 else 0.0
            pnl_inr = round(margin_used * leverage * pct_move, 2)
            terminal_status = "COMPLETED" if achieved_r > 0 else ("STOPPED" if achieved_r < 0 else "CANCELLED")

            await self._close_trade(terminal_status, close_price, reason, custom_r=achieved_r, custom_pnl=pnl_inr)
            price_fmt = format_price(coin, close_price)
            pnl_sign = "+" if pnl_inr >= 0 else ""
            return True, f"Closed {coin} at {price_fmt} ({pnl_sign}{achieved_r:+.2f}R | {pnl_sign}₹{pnl_inr:,.2f})!"
