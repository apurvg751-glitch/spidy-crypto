import logging
import time
from typing import Optional, Tuple, Dict, Any, List
from config.settings import settings
from storage.database import Database
from strategy.models.base_model import StrategyCandidate
from market_data.models import Candle

logger = logging.getLogger("spidy.strategy.reentry")


class ReentryManager:
    """
    SPIDY CRYPTO — Professional Re-Entry & Same-Market Cooldown Engine.
    Enforces:
    1. Fresh Structure Requirement (Zero reuse of consumed sweeps, BOS, CHoCH, OBs, FVGs, or retests).
    2. Setup Generation IDs (persisted & consumed permanently in SQLite).
    3. Per-Market Cooldown State Machine:
       TRADE_COMPLETED -> POST_TRADE_COOLDOWN -> WAITING_FOR_NEW_STRUCTURE ->
       NEW_SETUP_DETECTED -> VALIDATING -> READY.
    4. Strong Trend Continuation Exception (Configurable, requires brand-new structure).
    5. Overextension Guard (Rejects price chasing > 2.5x ATR).
    6. Comprehensive Re-entry Audit Trail.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self._memory_cooldowns: Dict[str, Dict[str, Any]] = {}
        self._load_from_db()

    def _load_from_db(self):
        """Loads persistent market cooldown states from SQLite on initialization."""
        try:
            persisted = self.db.get_all_market_cooldowns()
            for coin, data in persisted.items():
                self._memory_cooldowns[coin] = data
        except Exception as e:
            logger.warning(f"Failed to load market cooldowns from DB: {e}")

    @staticmethod
    def generate_setup_id(
        coin: str,
        model_id: str,
        direction: str,
        sweep_ts: Optional[int] = None,
        bos_ts: Optional[int] = None,
        ob_ts: Optional[int] = None,
        fvg_ts: Optional[int] = None,
        retest_ts: Optional[int] = None,
        retest_bar: Optional[int] = None
    ) -> str:
        """
        Creates a deterministic unique generation ID combining:
        symbol + strategy model + direction + structure timestamps.
        """
        s_ts = sweep_ts or 0
        b_ts = bos_ts or 0
        o_ts = ob_ts or 0
        f_ts = fvg_ts or 0
        r_id = retest_ts or retest_bar or 0
        return f"{coin}_{model_id}_{direction}_SW{s_ts}_BOS{b_ts}_OB{o_ts}_FVG{f_ts}_RT{r_id}"

    def register_trade_close(
        self,
        coin: str,
        trade_id: str,
        result: str,
        close_price: float,
        candidate_or_trade: Dict[str, Any]
    ):
        """
        Invoked immediately when a trade closes on a market.
        1. Permanently marks the originating setup generation as CONSUMED.
        2. Sets market state to POST_TRADE_COOLDOWN.
        """
        now = int(time.time())
        gen_id = candidate_or_trade.get("generation_id") or candidate_or_trade.get("setup_id", trade_id)
        model_id = candidate_or_trade.get("model_id", "MODEL_1")
        direction = candidate_or_trade.get("direction", "LONG")
        sweep_ts = candidate_or_trade.get("sweep_timestamp")
        bos_ts = candidate_or_trade.get("bos_timestamp")
        ob_ts = candidate_or_trade.get("ob_timestamp")
        fvg_ts = candidate_or_trade.get("fvg_timestamp")
        retest_ts = candidate_or_trade.get("retest_timestamp")

        # 1. Mark generation as CONSUMED in database
        self.db.mark_setup_consumed(
            generation_id=gen_id,
            coin=coin,
            model_id=model_id,
            direction=direction,
            sweep_ts=sweep_ts,
            bos_ts=bos_ts,
            ob_ts=ob_ts,
            fvg_ts=fvg_ts,
            retest_ts=retest_ts,
            trade_id=trade_id
        )

        # 2. Determine closed bar timestamp (5M bar = 300s alignment)
        closed_bar_ts = (now // 300) * 300
        last_struct_ts = max(filter(None, [sweep_ts, bos_ts, ob_ts, fvg_ts, retest_ts, now]))

        cooldown_bars = settings.SAME_MARKET_COOLDOWN_BARS

        # 3. Transition state to POST_TRADE_COOLDOWN
        state_data = {
            "coin": coin,
            "state": "POST_TRADE_COOLDOWN",
            "last_trade_id": trade_id,
            "last_trade_result": result,
            "closed_timestamp": now,
            "closed_bar_timestamp": closed_bar_ts,
            "cooldown_bars_required": cooldown_bars,
            "last_structure_timestamp": last_struct_ts,
            "updated_timestamp": now
        }
        self._memory_cooldowns[coin] = state_data
        self.db.set_market_cooldown(
            coin=coin,
            state="POST_TRADE_COOLDOWN",
            last_trade_id=trade_id,
            last_trade_result=result,
            closed_timestamp=now,
            closed_bar_timestamp=closed_bar_ts,
            cooldown_bars_required=cooldown_bars,
            last_structure_timestamp=last_struct_ts
        )

        logger.info(
            f"Market {coin} entered POST_TRADE_COOLDOWN ({cooldown_bars} bars required). "
            f"Consumed Setup Generation: {gen_id}"
        )

    def get_market_status(self, coin: str, current_bar_timestamp: Optional[int] = None) -> Dict[str, Any]:
        """
        Returns live re-entry and cooldown telemetry for the specified coin.
        """
        now = int(time.time())
        curr_bar = current_bar_timestamp or ((now // 300) * 300)
        cd = self._memory_cooldowns.get(coin)

        if not cd:
            return {
                "coin": coin,
                "state": "READY",
                "cooldown_remaining_bars": 0,
                "previous_setup_status": "NONE",
                "fresh_structure": "CONFIRMED",
                "trade_eligibility": "READY",
                "last_trade_result": "NONE"
            }

        closed_bar = cd.get("closed_bar_timestamp", curr_bar)
        required_bars = cd.get("cooldown_bars_required", settings.SAME_MARKET_COOLDOWN_BARS)
        bars_elapsed = max(0, (curr_bar - closed_bar) // 300)
        remaining_bars = max(0, required_bars - bars_elapsed)

        current_state = cd.get("state", "READY")

        # Update state progression if cooldown bars elapsed
        if current_state in ("TRADE_COMPLETED", "POST_TRADE_COOLDOWN") and remaining_bars == 0:
            current_state = "WAITING_FOR_NEW_STRUCTURE"
            cd["state"] = current_state
            self.db.set_market_cooldown(coin=coin, state=current_state)

        eligibility = "BLOCKED" if current_state in ("POST_TRADE_COOLDOWN", "WAITING_FOR_NEW_STRUCTURE") else "READY"
        fresh_str = "NOT YET" if current_state in ("POST_TRADE_COOLDOWN", "WAITING_FOR_NEW_STRUCTURE") else "CONFIRMED"

        return {
            "coin": coin,
            "state": current_state,
            "cooldown_remaining_bars": remaining_bars,
            "previous_setup_status": "CONSUMED",
            "fresh_structure": fresh_str,
            "trade_eligibility": eligibility,
            "last_trade_result": cd.get("last_trade_result", "NONE"),
            "last_trade_id": cd.get("last_trade_id")
        }

    def evaluate_candidate(
        self,
        candidate: StrategyCandidate,
        candles_5m: List[Candle],
        atr: float
    ) -> Tuple[bool, str, float]:
        """
        Comprehensive Re-entry Evaluation Gate.
        Returns: (is_approved: bool, reason: str, overextension_ratio: float)
        """
        coin = candidate.coin
        now = int(time.time())
        curr_bar = candles_5m[-1].time if candles_5m else ((now // 300) * 300)
        status = self.get_market_status(coin, curr_bar)
        remaining_bars = status["cooldown_remaining_bars"]
        current_state = status["state"]

        cd = self._memory_cooldowns.get(coin)
        prev_trade_id = cd.get("last_trade_id") if cd else None
        prev_result = cd.get("last_trade_result") if cd else None
        closed_ts = cd.get("closed_timestamp", 0) if cd else 0
        last_struct_ts = cd.get("last_structure_timestamp", 0) if cd else 0

        time_since_close = now - closed_ts if closed_ts > 0 else 999999
        bars_since_close = max(0, (curr_bar - cd.get("closed_bar_timestamp", curr_bar)) // 300) if cd else 999

        # Ensure generation_id is set
        if not candidate.generation_id:
            candidate.generation_id = self.generate_setup_id(
                coin=coin,
                model_id=candidate.model_id,
                direction=candidate.direction,
                sweep_ts=candidate.sweep_timestamp,
                bos_ts=candidate.bos_timestamp,
                ob_ts=candidate.ob_timestamp,
                fvg_ts=candidate.fvg_timestamp,
                retest_ts=candidate.retest_timestamp,
                retest_bar=candidate.retest_bar_index
            )

        # 1. Check if Setup Generation ID has already been CONSUMED
        if self.db.is_setup_consumed(candidate.generation_id):
            reason = "OLD_SETUP_ALREADY_CONSUMED"
            self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, False, candidate.generation_id, True, candidate.model_id, False, reason, 0.0)
            return False, reason, 0.0

        # 2. Check if any originating structural event was consumed
        if self.db.is_structure_event_consumed(
            coin=coin,
            sweep_ts=candidate.sweep_timestamp,
            bos_ts=candidate.bos_timestamp,
            ob_ts=candidate.ob_timestamp,
            fvg_ts=candidate.fvg_timestamp,
            retest_ts=candidate.retest_timestamp
        ):
            reason = "OLD_SETUP_ALREADY_CONSUMED"
            self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, False, candidate.generation_id, True, candidate.model_id, False, reason, 0.0)
            return False, reason, 0.0

        # 3. Check Cooldown Gate (with Strong Trend Continuation Exception)
        is_continuation = False
        if remaining_bars > 0:
            # Check Strong Trend Continuation Exception
            if settings.ALLOW_TREND_CONTINUATION_REENTRY:
                # Must have brand new BOS formed strictly after previous trade closed
                if candidate.bos_timestamp and candidate.bos_timestamp > closed_ts:
                    is_continuation = True
                    candidate.is_continuation_setup = True
                    logger.info(f"Market {coin} qualified for STRONG TREND CONTINUATION EXCEPTION (BOS: {candidate.bos_timestamp} > Close: {closed_ts})")
                else:
                    reason = f"COOLDOWN_ACTIVE ({remaining_bars} bars remaining)"
                    self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, False, candidate.generation_id, False, candidate.model_id, False, reason, 0.0)
                    return False, reason, 0.0
            else:
                reason = f"COOLDOWN_ACTIVE ({remaining_bars} bars remaining)"
                self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, False, candidate.generation_id, False, candidate.model_id, False, reason, 0.0)
                return False, reason, 0.0

        # 4. Fresh Structure Requirement Gate
        # Verify that candidate's newest structural event formed AFTER previous trade closed
        cand_struct_ts = max(filter(None, [
            candidate.sweep_timestamp,
            candidate.bos_timestamp,
            candidate.ob_timestamp,
            candidate.fvg_timestamp,
            candidate.retest_timestamp,
            candidate.detection_timestamp
        ]))

        if closed_ts > 0 and cand_struct_ts <= last_struct_ts and not is_continuation:
            reason = "NO_NEW_STRUCTURE"
            self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, False, candidate.generation_id, True, candidate.model_id, False, reason, 0.0)
            return False, reason, 0.0

        # 5. Overextension Guard (Anti-Price-Chasing)
        overextension_ratio = 0.0
        if candles_5m and atr > 0:
            # Determine structural anchor: local impulse origin from recent closed candles (last 5-6 bars)
            recent_closed = candles_5m[-6:-1] if len(candles_5m) > 6 else (candles_5m[:-1] if len(candles_5m) > 1 else candles_5m)
            ref_anchor = candidate.entry
            if candidate.direction == "LONG":
                lows = [c.low for c in recent_closed]
                ref_anchor = min(lows) if lows else candidate.entry
                dist = abs(candidate.entry - ref_anchor)
            else:
                highs = [c.high for c in recent_closed]
                ref_anchor = max(highs) if highs else candidate.entry
                dist = abs(ref_anchor - candidate.entry)

            overextension_ratio = round(dist / atr, 2)
            candidate.overextension_ratio = overextension_ratio

            if overextension_ratio > settings.MAX_OVEREXTENSION_ATR_RATIO:
                reason = f"OVEREXTENDED (Price {overextension_ratio}x ATR from structure > {settings.MAX_OVEREXTENSION_ATR_RATIO}x limit)"
                self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, remaining_bars, True, candidate.generation_id, False, candidate.model_id, False, reason, overextension_ratio)
                return False, reason, overextension_ratio

        # Passed all re-entry gates! Transition state to READY
        if cd:
            cd["state"] = "READY"
            self.db.set_market_cooldown(coin=coin, state="READY")

        self._audit(coin, prev_trade_id, prev_result, time_since_close, bars_since_close, 0, True, candidate.generation_id, False, candidate.model_id, True, None, overextension_ratio)
        return True, "QUALIFIED_FRESH_SETUP", overextension_ratio

    def _audit(
        self,
        coin: str,
        prev_id: Optional[str],
        prev_result: Optional[str],
        time_close: int,
        bars_close: int,
        rem_bars: int,
        new_struct: bool,
        cand_id: Optional[str],
        old_reused: bool,
        model_id: Optional[str],
        is_accepted: bool,
        rejection_reason: Optional[str],
        overext: float
    ):
        try:
            self.db.log_reentry_audit(
                coin=coin,
                previous_trade_id=prev_id,
                previous_trade_result=prev_result,
                time_since_close=time_close,
                bars_since_close=bars_close,
                cooldown_remaining_bars=rem_bars,
                new_structure_formed=new_struct,
                candidate_setup_id=cand_id,
                old_events_reused=old_reused,
                model_id=model_id,
                is_accepted=is_accepted,
                rejection_reason=rejection_reason,
                overextension_ratio=overext
            )
        except Exception as e:
            logger.debug(f"Audit log failed: {e}")
