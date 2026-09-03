import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from config.settings import settings


class Database:
    """SQLite Database wrapper for SPIDY CRYPTO setup history, state tracking, model statistics, and alert logs."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or settings.DB_PATH)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS setups (
                id TEXT PRIMARY KEY,
                coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                detection_timestamp INTEGER NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target_1 REAL NOT NULL,
                target_2 REAL NOT NULL,
                rr REAL NOT NULL,
                setup_score INTEGER NOT NULL,
                trend_15m TEXT NOT NULL,
                sweep_details TEXT,
                bos_details TEXT,
                volume_confirmation TEXT,
                reasons TEXT,
                is_selected INTEGER DEFAULT 0,
                is_rejected INTEGER DEFAULT 0,
                rejection_reason TEXT,
                trade_status TEXT NOT NULL,
                final_result TEXT,
                closing_timestamp INTEGER,
                model_id TEXT DEFAULT 'MODEL_1',
                model_name TEXT DEFAULT 'Liquidity Sweep Reversal',
                confirmations_count INTEGER DEFAULT 0,
                confirmations_rating TEXT DEFAULT 'QUALIFIED',
                achieved_r REAL DEFAULT 0.0,
                pnl REAL DEFAULT 0.0,
                mfe REAL DEFAULT 0.0,
                mae REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS active_trade (
                slot_id INTEGER PRIMARY KEY CHECK (slot_id = 1),
                setup_id TEXT NOT NULL,
                coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                target_1 REAL NOT NULL,
                target_2 REAL NOT NULL,
                rr REAL NOT NULL,
                setup_score INTEGER NOT NULL,
                trade_status TEXT NOT NULL,
                reasons TEXT,
                activated_timestamp INTEGER,
                last_updated_timestamp INTEGER,
                model_id TEXT DEFAULT 'MODEL_1',
                model_name TEXT DEFAULT 'Liquidity Sweep Reversal',
                confirmations_count INTEGER DEFAULT 0,
                peak_favorable_price REAL DEFAULT 0.0,
                peak_adverse_price REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS model_stats (
                model_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                trades_count INTEGER DEFAULT 0,
                wins_count INTEGER DEFAULT 0,
                losses_count INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0.0,
                total_r REAL DEFAULT 0.0,
                avg_r REAL DEFAULT 0.0,
                expectancy REAL DEFAULT 0.0,
                profit_factor REAL DEFAULT 0.0,
                max_drawdown REAL DEFAULT 0.0,
                avg_setup_score REAL DEFAULT 0.0,
                avg_confirmations REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS sent_alerts (
                alert_id TEXT PRIMARY KEY,
                coin TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS consumed_setups (
                generation_id TEXT PRIMARY KEY,
                coin TEXT NOT NULL,
                model_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                sweep_ts INTEGER,
                bos_ts INTEGER,
                ob_ts INTEGER,
                fvg_ts INTEGER,
                retest_ts INTEGER,
                consumed_timestamp INTEGER NOT NULL,
                trade_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_cooldowns (
                coin TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                last_trade_id TEXT,
                last_trade_result TEXT,
                closed_timestamp INTEGER,
                closed_bar_timestamp INTEGER,
                cooldown_bars_required INTEGER DEFAULT 4,
                last_structure_timestamp INTEGER,
                updated_timestamp INTEGER
            );

            CREATE TABLE IF NOT EXISTS reentry_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                previous_trade_id TEXT,
                previous_trade_result TEXT,
                time_since_close INTEGER,
                bars_since_close INTEGER,
                cooldown_remaining_bars INTEGER,
                new_structure_formed INTEGER,
                candidate_setup_id TEXT,
                old_events_reused INTEGER,
                model_id TEXT,
                is_accepted INTEGER,
                rejection_reason TEXT,
                overextension_ratio REAL
            );

            CREATE INDEX IF NOT EXISTS idx_consumed_coin ON consumed_setups(coin);
            CREATE INDEX IF NOT EXISTS idx_reentry_coin ON reentry_audits(coin);
            """)

            # Safe column migrations if existing database file was already created
            existing_setup_cols = [c[1] for c in conn.execute("PRAGMA table_info(setups);").fetchall()]
            new_setup_cols = [
                ("model_id", "TEXT DEFAULT 'MODEL_1'"),
                ("model_name", "TEXT DEFAULT 'Liquidity Sweep Reversal'"),
                ("confirmations_count", "INTEGER DEFAULT 0"),
                ("confirmations_rating", "TEXT DEFAULT 'QUALIFIED'"),
                ("achieved_r", "REAL DEFAULT 0.0"),
                ("pnl", "REAL DEFAULT 0.0"),
                ("mfe", "REAL DEFAULT 0.0"),
                ("mae", "REAL DEFAULT 0.0"),
            ]
            for col_name, col_type in new_setup_cols:
                if col_name not in existing_setup_cols:
                    conn.execute(f"ALTER TABLE setups ADD COLUMN {col_name} {col_type};")

            existing_trade_cols = [c[1] for c in conn.execute("PRAGMA table_info(active_trade);").fetchall()]
            new_trade_cols = [
                ("model_id", "TEXT DEFAULT 'MODEL_1'"),
                ("model_name", "TEXT DEFAULT 'Liquidity Sweep Reversal'"),
                ("confirmations_count", "INTEGER DEFAULT 0"),
                ("peak_favorable_price", "REAL DEFAULT 0.0"),
                ("peak_adverse_price", "REAL DEFAULT 0.0")
            ]
            for col_name, col_type in new_trade_cols:
                if col_name not in existing_trade_cols:
                    conn.execute(f"ALTER TABLE active_trade ADD COLUMN {col_name} {col_type};")

            # Create indices after columns are guaranteed to exist
            conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_setups_coin ON setups(coin);
            CREATE INDEX IF NOT EXISTS idx_setups_status ON setups(trade_status);
            CREATE INDEX IF NOT EXISTS idx_setups_model ON setups(model_id);
            CREATE INDEX IF NOT EXISTS idx_setups_ts ON setups(detection_timestamp DESC);
            """)

            # Seed default models into model_stats if empty
            count = conn.execute("SELECT COUNT(*) FROM model_stats;").fetchone()[0]
            if count == 0:
                models_seed = [
                    ("MODEL_1", "Liquidity Sweep Reversal"),
                    ("MODEL_2", "BOS Continuation"),
                    ("MODEL_3", "Order Block + FVG"),
                    ("MODEL_4", "CHoCH Reversal"),
                    ("MODEL_5", "Breakout Retest"),
                    ("MODEL_6", "Trend Pullback"),
                    ("MODEL_8", "Order Block + FVG Pullback"),
                    ("MODEL_9", "Liquidity Sweep Reversal ⭐"),
                    ("MODEL_10", "Institutional Sniper ⭐ (100% Confluence)"),
                    ("COMBINED", "Combined Portfolio")
                ]
                for m_id, m_name in models_seed:
                    conn.execute("""
                    INSERT OR IGNORE INTO model_stats (model_id, model_name)
                    VALUES (?, ?);
                    """, (m_id, m_name))
            else:
                # Ensure MODEL_8, MODEL_9, MODEL_10 exist even if model_stats was previously seeded
                for m_id, m_name in [
                    ("MODEL_8", "Order Block + FVG Pullback"),
                    ("MODEL_9", "Liquidity Sweep Reversal ⭐"),
                    ("MODEL_10", "Institutional Sniper ⭐ (100% Confluence)")
                ]:
                    conn.execute("""
                    INSERT OR IGNORE INTO model_stats (model_id, model_name)
                    VALUES (?, ?);
                    """, (m_id, m_name))

    def save_setup(
        self,
        setup_dict: dict[str, Any],
        is_selected: bool = False,
        is_rejected: bool = False,
        rejection_reason: str = "",
        trade_status: str = "SETUP FOUND"
    ):
        with self._get_connection() as conn:
            reasons_json = json.dumps(setup_dict.get("reasons", []))
            conn.execute("""
            INSERT INTO setups (
                id, coin, direction, detection_timestamp, entry, stop_loss,
                target_1, target_2, rr, setup_score, trend_15m, sweep_details,
                bos_details, volume_confirmation, reasons, is_selected, is_rejected,
                rejection_reason, trade_status, final_result, closing_timestamp,
                model_id, model_name, confirmations_count, confirmations_rating,
                achieved_r, pnl, mfe, mae
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                trade_status = excluded.trade_status,
                is_selected = excluded.is_selected,
                is_rejected = excluded.is_rejected,
                rejection_reason = excluded.rejection_reason,
                final_result = excluded.final_result,
                closing_timestamp = excluded.closing_timestamp,
                achieved_r = excluded.achieved_r,
                pnl = excluded.pnl,
                mfe = excluded.mfe,
                mae = excluded.mae;
            """, (
                setup_dict["id"],
                setup_dict["coin"],
                setup_dict["direction"],
                setup_dict["detection_timestamp"],
                setup_dict["entry"],
                setup_dict["stop_loss"],
                setup_dict["target_1"],
                setup_dict["target_2"],
                setup_dict["rr"],
                setup_dict["setup_score"],
                setup_dict.get("trend_15m", ""),
                setup_dict.get("sweep_details", ""),
                setup_dict.get("bos_details", ""),
                setup_dict.get("volume_details", ""),
                reasons_json,
                1 if is_selected else 0,
                1 if is_rejected else 0,
                rejection_reason,
                trade_status,
                setup_dict.get("final_result"),
                setup_dict.get("closing_timestamp"),
                setup_dict.get("model_id", "MODEL_1"),
                setup_dict.get("model_name", "Liquidity Sweep Reversal"),
                setup_dict.get("confirmations_count", 0),
                setup_dict.get("confirmations_rating", "QUALIFIED"),
                setup_dict.get("achieved_r", 0.0),
                setup_dict.get("pnl", 0.0),
                setup_dict.get("mfe", 0.0),
                setup_dict.get("mae", 0.0)
            ))

    def update_setup_status(
        self,
        setup_id: str,
        trade_status: str,
        final_result: Optional[str] = None,
        closing_timestamp: Optional[int] = None,
        achieved_r: Optional[float] = None,
        pnl: Optional[float] = None,
        mfe: Optional[float] = None,
        mae: Optional[float] = None
    ):
        with self._get_connection() as conn:
            conn.execute("""
            UPDATE setups
            SET trade_status = ?,
                final_result = COALESCE(?, final_result),
                closing_timestamp = COALESCE(?, closing_timestamp),
                achieved_r = COALESCE(?, achieved_r),
                pnl = COALESCE(?, pnl),
                mfe = COALESCE(?, mfe),
                mae = COALESCE(?, mae)
            WHERE id = ?;
            """, (trade_status, final_result, closing_timestamp, achieved_r, pnl, mfe, mae, setup_id))

    def update_model_stats(
        self,
        model_id: str,
        won: bool,
        achieved_r: float,
        score: int,
        confirmations: int
    ):
        """Updates persistent metrics for a specific model and combined portfolio."""
        with self._get_connection() as conn:
            for target_id in (model_id, "COMBINED"):
                row = conn.execute("SELECT * FROM model_stats WHERE model_id = ?;", (target_id,)).fetchone()
                if not row:
                    continue

                trades = row["trades_count"] + 1
                wins = row["wins_count"] + (1 if won else 0)
                losses = row["losses_count"] + (0 if won else 1)
                win_rate = round((wins / trades) * 100.0, 1)
                tot_r = round(row["total_r"] + achieved_r, 2)
                avg_r = round(tot_r / trades, 2)
                expectancy = avg_r

                # Drawdown approximation
                dd = max(row["max_drawdown"], abs(tot_r)) if tot_r < 0 else row["max_drawdown"]
                avg_score = round(((row["avg_setup_score"] * (trades - 1)) + score) / trades, 1)
                avg_conf = round(((row["avg_confirmations"] * (trades - 1)) + confirmations) / trades, 1)

                win_r = tot_r if tot_r > 0 else 0.0
                loss_r = abs(tot_r) if tot_r < 0 else 1e-4
                pf = round(win_r / max(loss_r, 1e-4), 2)

                conn.execute("""
                UPDATE model_stats
                SET trades_count = ?, wins_count = ?, losses_count = ?,
                    win_rate = ?, total_r = ?, avg_r = ?, expectancy = ?,
                    profit_factor = ?, max_drawdown = ?, avg_setup_score = ?,
                    avg_confirmations = ?
                WHERE model_id = ?;
                """, (trades, wins, losses, win_rate, tot_r, avg_r, expectancy, pf, dd, avg_score, avg_conf, target_id))

    def get_model_stats(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM model_stats ORDER BY model_id;").fetchall()
            return [dict(r) for r in rows]

    def get_history(self, limit: int = 100, coin: Optional[str] = None, model_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            query = "SELECT * FROM setups WHERE 1=1"
            params = []
            if coin:
                query += " AND coin = ?"
                params.append(coin)
            if model_id:
                query += " AND model_id = ?"
                params.append(model_id)
            query += " ORDER BY detection_timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("reasons"):
                    try:
                        d["reasons"] = json.loads(d["reasons"])
                    except Exception:
                        pass
                results.append(d)
            return results

    def get_active_trade(self) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM active_trade WHERE slot_id = 1;").fetchone()
            if not row:
                return None
            d = dict(row)
            if d.get("reasons"):
                try:
                    d["reasons"] = json.loads(d["reasons"])
                except Exception:
                    pass
            return d

    def set_active_trade(self, trade: dict[str, Any]):
        with self._get_connection() as conn:
            reasons_json = json.dumps(trade.get("reasons", []))
            conn.execute("""
            INSERT INTO active_trade (
                slot_id, setup_id, coin, direction, entry, stop_loss,
                target_1, target_2, rr, setup_score, trade_status, reasons,
                activated_timestamp, last_updated_timestamp, model_id, model_name,
                confirmations_count, peak_favorable_price, peak_adverse_price
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slot_id) DO UPDATE SET
                setup_id = excluded.setup_id,
                coin = excluded.coin,
                direction = excluded.direction,
                entry = excluded.entry,
                stop_loss = excluded.stop_loss,
                target_1 = excluded.target_1,
                target_2 = excluded.target_2,
                rr = excluded.rr,
                setup_score = excluded.setup_score,
                trade_status = excluded.trade_status,
                reasons = excluded.reasons,
                activated_timestamp = excluded.activated_timestamp,
                last_updated_timestamp = excluded.last_updated_timestamp,
                model_id = excluded.model_id,
                model_name = excluded.model_name,
                confirmations_count = excluded.confirmations_count,
                peak_favorable_price = excluded.peak_favorable_price,
                peak_adverse_price = excluded.peak_adverse_price;
            """, (
                trade["setup_id"],
                trade["coin"],
                trade["direction"],
                trade["entry"],
                trade["stop_loss"],
                trade["target_1"],
                trade["target_2"],
                trade["rr"],
                trade["setup_score"],
                trade["trade_status"],
                reasons_json,
                trade.get("activated_timestamp", int(time.time())),
                int(time.time()),
                trade.get("model_id", "MODEL_1"),
                trade.get("model_name", "Liquidity Sweep Reversal"),
                trade.get("confirmations_count", 0),
                trade.get("peak_favorable_price", trade["entry"]),
                trade.get("peak_adverse_price", trade["entry"])
            ))

    def clear_active_trade(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM active_trade WHERE slot_id = 1;")

    def is_alert_sent(self, alert_id: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute("SELECT 1 FROM sent_alerts WHERE alert_id = ?;", (alert_id,)).fetchone()
            return row is not None

    def record_alert_sent(self, alert_id: str, coin: str, alert_type: str):
        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR IGNORE INTO sent_alerts (alert_id, coin, alert_type, timestamp)
            VALUES (?, ?, ?, ?);
            """, (alert_id, coin, alert_type, int(time.time())))

    # -------------------------------------------------------------
    # Professional Re-Entry & Cooldown Methods
    # -------------------------------------------------------------

    def mark_setup_consumed(
        self,
        generation_id: str,
        coin: str,
        model_id: str,
        direction: str,
        sweep_ts: Optional[int],
        bos_ts: Optional[int],
        ob_ts: Optional[int],
        fvg_ts: Optional[int],
        retest_ts: Optional[int],
        trade_id: str
    ):
        """Marks a setup generation and its specific originating events as CONSUMED."""
        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO consumed_setups (
                generation_id, coin, model_id, direction,
                sweep_ts, bos_ts, ob_ts, fvg_ts, retest_ts,
                consumed_timestamp, trade_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                generation_id, coin, model_id, direction,
                sweep_ts, bos_ts, ob_ts, fvg_ts, retest_ts,
                int(time.time()), trade_id
            ))

    def is_setup_consumed(self, generation_id: str) -> bool:
        """Returns True if the exact generation ID has already been consumed."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT 1 FROM consumed_setups WHERE generation_id = ?;", (generation_id,)).fetchone()
            return row is not None

    def is_structure_event_consumed(
        self,
        coin: str,
        sweep_ts: Optional[int] = None,
        bos_ts: Optional[int] = None,
        ob_ts: Optional[int] = None,
        fvg_ts: Optional[int] = None,
        retest_ts: Optional[int] = None
    ) -> bool:
        """Checks if any individual originating structure event timestamp has already been consumed for this coin."""
        with self._get_connection() as conn:
            conditions = []
            params = [coin]

            if sweep_ts and sweep_ts > 0:
                conditions.append("sweep_ts = ?")
                params.append(sweep_ts)
            if bos_ts and bos_ts > 0:
                conditions.append("bos_ts = ?")
                params.append(bos_ts)
            if ob_ts and ob_ts > 0:
                conditions.append("ob_ts = ?")
                params.append(ob_ts)
            if fvg_ts and fvg_ts > 0:
                conditions.append("fvg_ts = ?")
                params.append(fvg_ts)
            if retest_ts and retest_ts > 0:
                conditions.append("retest_ts = ?")
                params.append(retest_ts)

            if not conditions:
                return False

            sql = f"SELECT 1 FROM consumed_setups WHERE coin = ? AND ({' OR '.join(conditions)}) LIMIT 1;"
            row = conn.execute(sql, tuple(params)).fetchone()
            return row is not None

    def get_market_cooldown(self, coin: str) -> Optional[dict[str, Any]]:
        """Retrieves persistent cooldown and re-entry state for a coin."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM market_cooldowns WHERE coin = ?;", (coin,)).fetchone()
            return dict(row) if row else None

    def set_market_cooldown(
        self,
        coin: str,
        state: str,
        last_trade_id: Optional[str] = None,
        last_trade_result: Optional[str] = None,
        closed_timestamp: Optional[int] = None,
        closed_bar_timestamp: Optional[int] = None,
        cooldown_bars_required: int = 4,
        last_structure_timestamp: Optional[int] = None
    ):
        """Updates persistent cooldown and re-entry state for a coin."""
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO market_cooldowns (
                coin, state, last_trade_id, last_trade_result,
                closed_timestamp, closed_bar_timestamp,
                cooldown_bars_required, last_structure_timestamp, updated_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(coin) DO UPDATE SET
                state = excluded.state,
                last_trade_id = COALESCE(excluded.last_trade_id, market_cooldowns.last_trade_id),
                last_trade_result = COALESCE(excluded.last_trade_result, market_cooldowns.last_trade_result),
                closed_timestamp = COALESCE(excluded.closed_timestamp, market_cooldowns.closed_timestamp),
                closed_bar_timestamp = COALESCE(excluded.closed_bar_timestamp, market_cooldowns.closed_bar_timestamp),
                cooldown_bars_required = excluded.cooldown_bars_required,
                last_structure_timestamp = COALESCE(excluded.last_structure_timestamp, market_cooldowns.last_structure_timestamp),
                updated_timestamp = excluded.updated_timestamp;
            """, (
                coin, state, last_trade_id, last_trade_result,
                closed_timestamp, closed_bar_timestamp,
                cooldown_bars_required, last_structure_timestamp, int(time.time())
            ))

    def get_all_market_cooldowns(self) -> dict[str, dict[str, Any]]:
        """Returns all persistent cooldown states mapped by coin."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM market_cooldowns;").fetchall()
            return {r["coin"]: dict(r) for r in rows}

    def log_reentry_audit(
        self,
        coin: str,
        previous_trade_id: Optional[str],
        previous_trade_result: Optional[str],
        time_since_close: int,
        bars_since_close: int,
        cooldown_remaining_bars: int,
        new_structure_formed: bool,
        candidate_setup_id: Optional[str],
        old_events_reused: bool,
        model_id: Optional[str],
        is_accepted: bool,
        rejection_reason: Optional[str],
        overextension_ratio: float = 0.0
    ):
        """Persists a detailed audit row for every re-entry evaluation."""
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO reentry_audits (
                coin, timestamp, previous_trade_id, previous_trade_result,
                time_since_close, bars_since_close, cooldown_remaining_bars,
                new_structure_formed, candidate_setup_id, old_events_reused,
                model_id, is_accepted, rejection_reason, overextension_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                coin, int(time.time()), previous_trade_id, previous_trade_result,
                time_since_close, bars_since_close, cooldown_remaining_bars,
                1 if new_structure_formed else 0, candidate_setup_id,
                1 if old_events_reused else 0, model_id,
                1 if is_accepted else 0, rejection_reason, overextension_ratio
            ))

    def reset_all_data(self):
        """Clears all setups, active trade, alerts, cooldowns, and model statistics for a fresh state."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM active_trade;")
            conn.execute("DELETE FROM setups;")
            conn.execute("DELETE FROM sent_alerts;")
            conn.execute("DELETE FROM consumed_setups;")
            conn.execute("DELETE FROM market_cooldowns;")
            conn.execute("DELETE FROM reentry_audits;")
            conn.execute("DELETE FROM model_stats;")
