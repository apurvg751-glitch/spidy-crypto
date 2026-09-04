import sys
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from market_data.feed_manager import FeedManager
from market_data.models import Candle
from strategy.setup_detector import SetupDetector, DetectedSetup
from strategy.candidate_ranking import CandidateRankingEngine
from trade_manager.manager import TradeManager
from storage.database import Database
from telegram.notifier import TelegramNotifier
from backtesting.engine import BacktestEngine
from backtesting.out_of_sample import OutOfSampleValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("spidy.server")

# Global instances
db = Database()
telegram = TelegramNotifier(db=db)
trade_manager = TradeManager(db=db, telegram=telegram)
feed_manager: Optional[FeedManager] = None
connected_websockets: list[WebSocket] = []
scan_task: Optional[asyncio.Task] = None


async def broadcast_ws(payload: dict[str, Any]):
    """Broadcasts a JSON message to all active WebSocket clients."""
    disconnected = []
    text = json.dumps(payload)
    for ws in connected_websockets:
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.append(ws)
    for dead in disconnected:
        if dead in connected_websockets:
            connected_websockets.remove(dead)


def on_candle_closed(symbol: str, resolution: str, candle: Candle):
    """Callback when a candle closes on any monitored market."""
    logger.info(f"Candle closed [{symbol} {resolution}]: Close={candle.close}")
    asyncio.create_task(broadcast_ws({
        "type": "CANDLE_CLOSED",
        "symbol": symbol,
        "resolution": resolution,
        "candle": candle.model_dump()
    }))
    asyncio.create_task(run_market_scan())


def on_tick(symbol: str, price: float):
    """Callback on real-time price tick."""
    asyncio.create_task(trade_manager.update_price(symbol, price))
    asyncio.create_task(broadcast_ws({
        "type": "PRICE_TICK",
        "symbol": symbol,
        "price": price
    }))


last_evaluated_candle_time: dict[str, int] = {}


async def run_market_scan(force: bool = False):
    """Scans ETHUSD, BTCUSD, and SOLUSD on closed 5M candles (strictly once per bar)."""
    if not feed_manager:
        return

    all_candidates = []

    for symbol in settings.SYMBOLS:
        m = feed_manager.get_market_state(symbol)
        if not m or not m.candles_5m or not m.candles_15m:
            continue

        # Closed-bar timestamp lock: Only evaluate when a new 5M candle has closed!
        closed_bar_time = m.candles_5m[-2].time if len(m.candles_5m) > 1 else (m.candles_5m[-1].time if m.candles_5m else 0)
        if not force and closed_bar_time > 0 and last_evaluated_candle_time.get(symbol) == closed_bar_time:
            continue  # Already evaluated this 5M bar; prevent duplicate mid-candle flipping

        if closed_bar_time > 0:
            last_evaluated_candle_time[symbol] = closed_bar_time

        # Evaluate all institutional strategy models on closed bars
        model_candidates = SetupDetector.evaluate_all_models(m)
        all_candidates.extend(model_candidates)

    if all_candidates:
        await trade_manager.process_candidates(all_candidates)
        await broadcast_full_status()


async def broadcast_full_status():
    status = get_system_status()
    await broadcast_ws({
        "type": "STATUS_UPDATE",
        "data": status
    })


def get_system_status() -> dict[str, Any]:
    states = {}
    if feed_manager:
        for sym, m in feed_manager.get_all_states().items():
            states[sym] = {
                "symbol": sym,
                "current_price": m.current_price,
                "is_stale": m.is_stale,
                "connection_status": m.connection_status,
                "candles_5m_count": len(m.candles_5m),
                "candles_15m_count": len(m.candles_15m),
                "candles_1h_count": len(m.candles_1h),
                "candles_4h_count": len(m.candles_4h),
                "mtf_context": m.mtf_context.model_dump() if m.mtf_context else None
            }

    history = db.get_history(limit=50)
    trade_summary = trade_manager.get_current_status_summary()
    model_stats = db.get_model_stats()

    return {
        "global_status": trade_summary["global_status"],
        "active_trade": trade_summary["active_trade"],
        "reentry_status": trade_summary.get("reentry_status", {}),
        "markets": states,
        "history": history,
        "model_stats": model_stats
    }


async def background_scanner_loop():
    """Periodic background scan every 10 seconds."""
    while True:
        try:
            await asyncio.sleep(10)
            await run_market_scan()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background scanner: {e}")


async def render_keepalive_loop():
    """Keeps Render cloud free instance from spinning down."""
    import os
    import httpx
    url = os.getenv("RENDER_EXTERNAL_URL") or "https://spidy-crypto.onrender.com"
    logger.info(f"Render cloud keepalive activated for: {url}")
    while True:
        try:
            await asyncio.sleep(300)  # ping every 5 mins to prevent Render 15-min idle sleep
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{url}/api/status", timeout=10.0)
                logger.debug(f"Render self-ping status: {res.status_code}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Render self-ping error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global feed_manager, scan_task
    logger.info("Starting SPIDY CRYPTO Core Service (Trading Intelligence Upgrade)...")

    feed_manager = FeedManager(
        on_candle_closed=on_candle_closed,
        on_tick=on_tick
    )
    await feed_manager.start()

    scan_task = asyncio.create_task(background_scanner_loop())
    keepalive_task = asyncio.create_task(render_keepalive_loop())

    from telegram.bot_listener import TelegramBotListener
    bot_listener = TelegramBotListener(trade_manager=trade_manager, feed_manager=feed_manager)
    listener_task = asyncio.create_task(bot_listener.start_polling())

    yield

    logger.info("Shutting down SPIDY CRYPTO...")
    if scan_task:
        scan_task.cancel()
    if keepalive_task:
        keepalive_task.cancel()
    if listener_task:
        listener_task.cancel()
    await bot_listener.close()
    if feed_manager:
        await feed_manager.stop()
    await telegram.close()


app = FastAPI(title="SPIDY CRYPTO", lifespan=lifespan)

static_dir = Path(__file__).resolve().parent / "ui" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = Path(__file__).resolve().parent / "ui" / "templates" / "index.html"
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status():
    return get_system_status()


@app.get("/api/model_stats")
async def api_model_stats():
    return {"model_stats": db.get_model_stats()}


@app.get("/api/history")
async def api_history(coin: Optional[str] = None, model_id: Optional[str] = None, limit: int = 50):
    return {"history": db.get_history(limit=limit, coin=coin, model_id=model_id)}


@app.get("/api/candles/{symbol}")
async def api_candles(symbol: str, resolution: str = "5m", limit: int = 50):
    if not feed_manager:
        return {"candles": []}
    m = feed_manager.get_market_state(symbol.upper())
    if not m:
        return {"candles": []}

    if resolution == "5m":
        candles = m.candles_5m
    elif resolution == "15m":
        candles = m.candles_15m
    elif resolution == "1h":
        candles = m.candles_1h
    elif resolution == "4h":
        candles = m.candles_4h
    else:
        candles = m.candles_5m

    usable = candles[-limit:] if len(candles) >= limit else candles
    return {"symbol": symbol, "resolution": resolution, "candles": [c.model_dump() for c in usable]}


@app.post("/api/trigger_scan")
async def api_trigger_scan():
    """Executes a full live scan across all 9 models on all 3 coins, returning detailed telemetry."""
    if not feed_manager:
        return {"status": "error", "message": "Feed manager is not initialized"}

    await run_market_scan()

    # Collect diagnostic status for each coin to return to user
    coin_summaries = []
    candidates_count = 0

    for symbol in settings.SYMBOLS:
        m = feed_manager.get_market_state(symbol)
        if not m or not m.candles_5m:
            coin_summaries.append({
                "symbol": symbol,
                "status": "No candle data",
                "confirmations": "-/7",
                "best_model": "-"
            })
            continue

        cands = SetupDetector.evaluate_all_models(m)
        if cands:
            candidates_count += len(cands)
            best = max(cands, key=lambda c: c.setup_score)
            coin_summaries.append({
                "symbol": symbol,
                "status": f"QUALIFIED ({best.direction})",
                "confirmations": f"{best.confirmations.passed_count}/7",
                "best_model": best.model_name,
                "score": best.setup_score
            })
        else:
            # Check highest confirmation count from standard confirmation engine
            c5 = m.candles_5m
            c15 = m.candles_15m or c5
            from strategy.confirmation_engine import ConfirmationEngine
            confs = ConfirmationEngine.evaluate(
                direction="LONG" if (m.mtf_context and m.mtf_context.exec_context_15m == "Bullish") else "SHORT",
                candles_5m=c5,
                candles_15m=c15,
                mtf_context=m.mtf_context
            )
            coin_summaries.append({
                "symbol": symbol,
                "status": f"Monitoring ({confs.rating})",
                "confirmations": f"{confs.passed_count}/7",
                "best_model": "Scanning 9 Models",
                "score": 70 + (confs.passed_count * 4)
            })

    active_info = f"Locked on {trade_manager.active_trade['coin']}" if trade_manager.active_trade else "Slot Open (0/1)"

    return {
        "status": "success",
        "message": f"Scanned 9 Models across ETH, BTC, SOL (27 checks total). {active_info}.",
        "candidates_found": candidates_count,
        "active_lock": active_info,
        "results": coin_summaries
    }


@app.post("/api/backtest/run")
async def api_backtest_run(symbol: Optional[str] = Query(None)):
    """Executes backtest engine on cached historical candles for a specific coin or across markets."""
    if not feed_manager:
        return {"status": "feed_not_ready"}

    active_symbols = [symbol.upper()] if symbol and symbol.upper() in settings.SYMBOLS else settings.SYMBOLS
    candles_5m = {s: feed_manager.get_market_state(s).candles_5m for s in active_symbols if feed_manager.get_market_state(s)}
    candles_15m = {s: feed_manager.get_market_state(s).candles_15m for s in active_symbols if feed_manager.get_market_state(s)}

    engine = BacktestEngine(symbols=active_symbols)
    trades, metrics = engine.run(candles_5m, candles_15m)

    # Compute comprehensive per-market stats for each coin independently
    by_market = {}
    for s in settings.SYMBOLS:
        m = feed_manager.get_market_state(s)
        if m and m.candles_5m and m.candles_15m:
            s_engine = BacktestEngine(symbols=[s])
            s_trades, s_metrics = s_engine.run({s: m.candles_5m}, {s: m.candles_15m})
            by_market[s] = {
                "trades": s_metrics.total_trades,
                "wins": s_metrics.wins,
                "win_rate": s_metrics.win_rate,
                "total_r": s_metrics.total_r_gain,
                "profit_factor": s_metrics.profit_factor
            }
            # Record trades into model_stats so table is filled with real data
            for t in s_trades:
                db.update_model_stats(
                    model_id=t.model_id,
                    won=t.won,
                    achieved_r=t.achieved_r,
                    score=t.setup_score,
                    confirmations=t.confirmations_count
                )

    model_stats = db.get_model_stats()

    return {
        "status": "completed",
        "selected_symbol": symbol.upper() if symbol else "ALL",
        "trades_count": len(trades),
        "metrics": metrics.model_dump(),
        "by_market": by_market,
        "model_stats": model_stats,
        "recent_trades": [t.model_dump() for t in trades[-15:]]
    }


@app.post("/api/backtest/validate")
async def api_backtest_validate(symbol: Optional[str] = Query(None)):
    """Runs train vs out-of-sample validation for a specific coin or all coins."""
    if not feed_manager:
        return {"status": "feed_not_ready"}

    active_symbols = [symbol.upper()] if symbol and symbol.upper() in settings.SYMBOLS else settings.SYMBOLS
    candles_5m = {s: feed_manager.get_market_state(s).candles_5m for s in active_symbols if feed_manager.get_market_state(s)}
    candles_15m = {s: feed_manager.get_market_state(s).candles_15m for s in active_symbols if feed_manager.get_market_state(s)}

    result = OutOfSampleValidator.run_validation(candles_5m, candles_15m, train_ratio=0.70)
    result["selected_symbol"] = symbol.upper() if symbol else "ALL"
    return result


@app.get("/api/analysis/{symbol}")
async def api_analysis(symbol: str):
    """
    Returns real-time structural analysis, technical variables,
    confirmations, and state progression for the specific coin.
    """
    from structure.swings import find_swings
    from structure.liquidity import LiquidityEngine
    from structure.bos_choch import BosChochEngine
    from structure.retest import RetestEngine
    from structure.order_blocks import OrderBlockEngine
    from structure.fvg import FvgEngine
    from strategy.confirmation_engine import ConfirmationEngine
    from indicators.atr import calculate_atr
    from indicators.volume import calculate_rvol

    sym = symbol.upper()
    if not feed_manager:
        return {"error": "Feed manager not ready"}

    m = feed_manager.get_market_state(sym)
    if not m or not m.candles_5m:
        return {"error": f"No candles for {sym}"}

    c5 = m.candles_5m
    c15 = m.candles_15m or c5
    price = m.current_price or c5[-1].close
    atr = calculate_atr(c5, 14)
    rvol = calculate_rvol(c5, 20)

    # Check if this coin has an active trade
    is_active = (trade_manager.active_trade is not None and trade_manager.active_trade.get("coin") == sym)
    active_t = trade_manager.active_trade if is_active else None

    # Structural components
    swings = find_swings(c5, lookback=3)
    eq_pools = LiquidityEngine.find_equal_highs_lows(swings, tolerance_pct=0.20)
    sweep_eq = LiquidityEngine.detect_eqh_eql_sweep(c5, eq_pools, search_bars=8)
    sweep_std = LiquidityEngine.detect_liquidity_sweep(c5, swings, search_bars=8)
    sweep = sweep_eq if sweep_eq.detected else sweep_std
    bos = BosChochEngine.detect(c5, swings, search_bars=8)

    obs = OrderBlockEngine.find_order_blocks(sym, c5)
    active_ob = OrderBlockEngine.get_active_ob(obs, "LONG")
    fvgs = FvgEngine.find_fvgs(sym, c5)
    active_fvg = FvgEngine.get_active_fvg(fvgs, "LONG")

    confs = ConfirmationEngine.evaluate(
        direction="LONG" if (m.mtf_context and m.mtf_context.exec_context_15m == "Bullish") else "SHORT",
        candles_5m=c5,
        candles_15m=c15,
        mtf_context=m.mtf_context,
        active_ob=active_ob,
        active_fvg=active_fvg
    )

    from structure.equilibrium import EquilibriumEngine
    from indicators.displacement import DisplacementEngine
    from structure.barrier_engine import BarrierEngine
    from strategy.setup_grading import SetupGradingEngine

    dr = EquilibriumEngine.calculate_range(c15 or c5)
    disp = DisplacementEngine.evaluate(c5)

    direction = active_t.get("direction") if is_active else ("LONG" if (m.mtf_context and m.mtf_context.exec_context_15m == "Bullish") else "SHORT")
    base_score = active_t.get("setup_score", 70 + (confs.passed_count * 4)) if is_active else (70 + (confs.passed_count * 4))

    barrier_res = BarrierEngine.validate_room_to_run(
        direction=direction,
        current_price=price,
        candles_15m=c15,
        atr=atr,
        dealing_range=dr
    )

    grade_res = SetupGradingEngine.grade_setup(
        direction=direction,
        current_price=price,
        setup_score=base_score,
        confirmations=confs,
        mtf_context=m.mtf_context,
        dealing_range=dr,
        displacement=disp
    )

    # Dynamic progression steps for this specific coin
    steps = [
        {
            "id": "pd_range",
            "name": "DEALING RANGE",
            "passed": grade_res.pd_zone_ok,
            "label": f"{dr.zone} ({dr.current_position_pct*100:.0f}%) ✓" if dr else "PD RANGE ⏳",
            "desc": dr.description if dr else "Calculating equilibrium"
        },
        {
            "id": "eq_pool",
            "name": "EQ POOL",
            "passed": len(eq_pools) > 0,
            "label": f"EQ POOL ({len(eq_pools)}) ✓" if eq_pools else "EQ POOL ⏳",
            "desc": eq_pools[0].description if eq_pools else "Scanning for Equal Highs/Lows"
        },
        {
            "id": "sweep",
            "name": "SWEEP",
            "passed": sweep.detected,
            "label": "SWEEP ✓" if sweep.detected else "SWEEP ⏳",
            "desc": sweep.description if sweep.detected else "Watching key liquidity pools"
        },
        {
            "id": "bos",
            "name": "BOS / CHOCH",
            "passed": bos.detected,
            "label": f"{bos.event_type or 'BOS'} ✓" if bos.detected else "BOS ⏳",
            "desc": bos.description if bos.detected else "Awaiting structure shift"
        },
        {
            "id": "disp",
            "name": "DISPLACEMENT",
            "passed": disp.detected,
            "label": "DISPLACEMENT ✓" if disp.detected else "DISPLACEMENT ⏳",
            "desc": disp.description
        },
        {
            "id": "conf",
            "name": "CONFIRMATIONS",
            "passed": confs.is_qualified,
            "label": f"CONFIRMATION ({confs.passed_count}/7) ✓" if confs.is_qualified else f"CONFIRMATION ({confs.passed_count}/7) ⏳",
            "desc": f"{confs.rating} ({confs.passed_count}/7 criteria met)"
        },
        {
            "id": "ready",
            "name": "GRADE",
            "passed": is_active or grade_res.is_tradeable,
            "label": "ACTIVE TRADE" if is_active else (grade_res.badge if grade_res.is_tradeable else "WATCHING"),
            "desc": f"Grade: {grade_res.grade} | Policy: {'Strict Risk (Tight SL / Quick TP)' if grade_res.grade == 'B+' else 'Institutional Conviction'}"
        }
    ]

    from structure.target_snapper import TargetSnapper
    from structure.kill_zones import KillZoneEngine
    from indicators.smt_divergence import SMTDivergenceEngine
    from structure.session_vwap import SessionVWAPEngine

    kz = KillZoneEngine.evaluate(c15)
    vwap_res = SessionVWAPEngine.calculate(c5, price)
    btc_m = feed_manager.get_market_state("BTCUSD") if feed_manager else None
    eth_m = feed_manager.get_market_state("ETHUSD") if feed_manager else None
    smt = SMTDivergenceEngine.evaluate(
        btc_m.candles_15m if btc_m else [],
        eth_m.candles_15m if eth_m else []
    )

    # Calculate coin-tailored levels anchored to real market structure
    if is_active:
        entry = active_t["entry"]
        stop = active_t["stop_loss"]
        t1 = active_t["target_1"]
        t2 = active_t["target_2"]
        rr = active_t["rr"]
        score = active_t["setup_score"]
        model_name = active_t.get("model_name", "Liquidity Sweep Reversal")
        status_label = active_t["trade_status"]
        current_grade = active_t.get("grade", grade_res.grade)
    else:
        current_grade = grade_res.grade if grade_res.is_tradeable else "B+"
        raw_sl = round(price - (atr * 0.8) if direction == "LONG" else price + (atr * 0.8), 2)
        snapped = TargetSnapper.snap_targets(
            direction=direction,
            entry=price,
            stop_loss=raw_sl,
            candles_15m=c15,
            dealing_range=dr,
            min_rr=1.6
        )
        entry = snapped.entry
        stop = snapped.stop_loss
        t1 = snapped.target_1
        t2 = snapped.target_2
        rr = snapped.rr_2
        score = base_score
        model_name = "Model 1: Liquidity Sweep Reversal"
        status_label = "WATCHING"

    policy_label = "Strict Risk (Tight SL 0.15 ATR / Quick 1.6R TP / Fast BE)" if current_grade == "B+" else "Institutional Conviction (Full 2.5R Target)"

    return {
        "symbol": sym,
        "price": price,
        "atr": round(atr, 2),
        "rvol": round(rvol, 2),
        "direction": direction,
        "model_name": model_name,
        "status": status_label,
        "is_active_trade": is_active,
        "score": score,
        "grade": current_grade,
        "grade_badge": grade_res.badge if not is_active else f"GRADE: {current_grade}",
        "policy": policy_label,
        "confirmations_count": confs.passed_count,
        "confirmations_rating": confs.rating,
        "dealing_range": dr.model_dump() if dr else None,
        "displacement": disp.model_dump() if disp else None,
        "barrier": barrier_res.model_dump(),
        "kill_zone": kz.model_dump(),
        "smt": smt.model_dump(),
        "vwap": vwap_res.__dict__ if vwap_res else None,
        "levels": {
            "entry": round(entry, 2),
            "stop_loss": round(stop, 2),
            "target_1": round(t1, 2),
            "target_2": round(t2, 2),
            "rr": rr,
            "margin": f"₹{int(settings.ACCOUNT_EQUITY):,} (1x)"
        },
        "progression_steps": steps,
        "reasons": [
            f"4H Macro: {m.mtf_context.macro_bias_4h if m.mtf_context else 'Neutral'} | 1H: {m.mtf_context.trend_1h if m.mtf_context else 'Neutral'}",
            f"Session Window: {kz.description}",
            f"SMT Intermarket: {smt.description}",
            f"Value Area: {vwap_res.description}" if vwap_res else "Value Area: Calibrating",
            f"Dealing Range: {dr.description if dr else 'Neutral'}",
            f"Structural Clearance: {barrier_res.reason}",
            f"Institutional Displacement: {disp.description}",
            f"EQ Highs/Lows: {eq_pools[0].description if eq_pools else 'No adjacent equal extremes'}",
            f"Liquidity Sweep: {sweep.description if sweep.detected else 'Watching key BSL/SSL levels'}",
            f"BOS / CHoCH: {bos.description if bos.detected else 'Structure intact'}",
            f"Order Block: {'Demand OB [' + str(round(active_ob.bottom, 2)) + ' - ' + str(round(active_ob.top, 2)) + ']' if active_ob else 'No active OB'}",
            f"FVG: {'Fair Value Gap [' + str(round(active_fvg.bottom, 2)) + ' - ' + str(round(active_fvg.top, 2)) + ']' if active_fvg else 'No active FVG'}",
            f"Grade Policy: {policy_label} | Confirms: {confs.passed_count}/7"
        ]
    }


@app.get("/api/vwap/{symbol}")
async def api_get_vwap(symbol: str):
    """Returns session-anchored VWAP, VAH, VAL, and POC for a given symbol."""
    sym = symbol.upper()
    if not feed_manager:
        raise HTTPException(status_code=503, detail="Feed manager offline")
    m = feed_manager.get_market_state(sym)
    if not m or not m.candles_5m:
        raise HTTPException(status_code=404, detail="Candles unavailable")

    from structure.session_vwap import SessionVWAPEngine
    res = SessionVWAPEngine.calculate(m.candles_5m, m.current_price)
    if not res:
        raise HTTPException(status_code=404, detail="Insufficient session data for VWAP")
    return res.__dict__


@app.get("/journal", response_class=HTMLResponse)
async def get_journal_page():
    """Renders the standalone Cyberpunk Daily Trade Journal page."""
    from journal.trade_journal import TradeJournalEngine
    return HTMLResponse(content=TradeJournalEngine.generate_html_page())


@app.get("/api/journal/today")
async def get_journal_api():
    """Returns today's performance analytics and trade audit."""
    from journal.trade_journal import TradeJournalEngine
    return TradeJournalEngine.get_daily_trades()


@app.get("/api/reentry_status")
async def get_reentry_status():
    """Returns per-market re-entry and cooldown status for all symbols."""
    if not trade_manager or not hasattr(trade_manager, "reentry_manager"):
        return {}
    return {s: trade_manager.reentry_manager.get_market_status(s) for s in settings.SYMBOLS}


@app.get("/api/reentry_status/{symbol}")
async def get_symbol_reentry_status(symbol: str):
    """Returns re-entry and cooldown status for a specific symbol."""
    sym = symbol.upper()
    if not trade_manager or not hasattr(trade_manager, "reentry_manager"):
        raise HTTPException(status_code=503, detail="Trade manager not ready")
    return trade_manager.reentry_manager.get_market_status(sym)


@app.post("/api/close_active_trade")
async def api_close_active_trade():
    """Manually cancels and releases any active or waiting trade in the bot."""
    closed_coin = None
    if trade_manager.active_trade:
        closed_coin = trade_manager.active_trade["coin"]
        success, close_msg = await trade_manager.emergency_close("MANUALLY CLOSED BY USER")

    # Clean any lingering waiting setups in DB without overwriting completed trades
    with db._get_connection() as conn:
        conn.execute("""
        UPDATE setups
        SET trade_status = 'CANCELLED', final_result = 'CANCELLED BEFORE EXECUTION'
        WHERE trade_status IN ('WAITING', 'TRIGGERED', 'PENDING');
        """)
        conn.execute("DELETE FROM active_trade;")

    trade_manager.active_trade = None
    trade_manager.global_status = "WATCHING"

    # Send Telegram Notification to Apurv
    try:
        msg = (
            "🛑 *ALL TRADES CANCELLED*\n\n"
            f"• Action: All active and waiting trades cancelled\n"
            f"• Affected Coin: *{closed_coin or 'None'}*\n"
            f"• Global Slot: *OPEN (0/1)*\n"
            f"• Bot Status: *WATCHING*\n\n"
            "Bot is actively monitoring ETH, BTC, and SOL for new institutional setups."
        )
        await telegram.send_message(msg)
    except Exception as e:
        logger.warning(f"Telegram notice error: {e}")

    await broadcast_full_status()

    if closed_coin:
        return {"status": "trade_closed", "message": f"Active trade on {closed_coin} cancelled. Global slot is now OPEN."}
    return {"status": "all_cleared", "message": "All trades cancelled and cleared. Global slot is OPEN."}


@app.post("/api/reset")
async def api_reset():
    """Wipes all setups, active trade, alerts, and cooldowns for a fresh start."""
    db.reset_all_data()
    trade_manager.active_trade = None
    trade_manager.global_status = "WATCHING"
    await broadcast_full_status()
    return {"status": "success", "message": "SPIDY CRYPTO system reset complete. All trade history and cooldowns cleared."}


@app.post("/api/simulate_setup")
async def api_simulate_setup(
    symbol: str = Query("ETHUSD"),
    direction: str = Query("LONG"),
    model_id: str = Query("MODEL_1"),
    force: bool = Query(True)
):
    """Test endpoint to inject a simulated candidate setup. Overrides existing trade if force=True."""
    import time
    m = feed_manager.get_market_state(symbol) if feed_manager else None
    price = m.current_price if (m and m.current_price > 0) else 0.0
    if price <= 0:
        # Fetch live price directly from Delta REST
        try:
            import httpx
            async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
                res = await client.get("https://api.india.delta.exchange/v2/tickers")
                if res.status_code == 200:
                    for item in res.json().get("result", []):
                        if item.get("symbol") == symbol:
                            price = float(item.get("close") or item.get("mark_price") or 0.0)
                            break
        except Exception:
            pass
    if price <= 0:
        price = (m.candles_5m[-1].close if m and m.candles_5m else 100.0)
    now = int(time.time())

    # If force=True, release previous trade first
    if force and trade_manager.active_trade:
        db.clear_active_trade()
        trade_manager.active_trade = None
        trade_manager.global_status = "WATCHING"

    model_names = {
        "MODEL_1": "Liquidity Sweep Reversal",
        "MODEL_2": "BOS Continuation",
        "MODEL_3": "Order Block + FVG",
        "MODEL_4": "CHoCH Reversal",
        "MODEL_5": "Breakout Retest",
        "MODEL_6": "Trend Pullback",
        "MODEL_8": "Order Block + FVG Pullback",
        "MODEL_9": "Liquidity Sweep Reversal ⭐",
        "MODEL_10": "Institutional Sniper ⭐ (100% Confluence)"
    }
    m_name = model_names.get(model_id, "Institutional Sniper ⭐ (100% Confluence)")

    risk = price * 0.008
    decimals = 4 if symbol == "XRPUSD" else 2
    if direction.upper() == "LONG":
        entry = round(price, decimals)
        stop = round(price - risk, decimals)
        t1 = round(entry + risk * 1.8, decimals)
        t2 = round(entry + risk * 2.5, decimals)
    else:
        entry = round(price, decimals)
        stop = round(price + risk, decimals)
        t1 = round(entry - risk * 1.8, decimals)
        t2 = round(entry - risk * 2.5, decimals)

    setup = DetectedSetup(
        id=f"SIM_{symbol}_{model_id}_{direction}_{now}",
        coin=symbol,
        direction=direction.upper(),
        detection_timestamp=now,
        entry=entry,
        stop_loss=stop,
        target_1=t1,
        target_2=t2,
        rr=2.5,
        setup_score=100 if model_id == "MODEL_10" else 88,
        score_breakdown={
            "trend_score": 25, "sweep_score": 25, "bos_score": 20, "volume_score": 10, "rr_score": 8, "total_score": 100 if model_id == "MODEL_10" else 88
        } if model_id != "MODEL_10" else {
            "htf_macro_score": 20, "liquidity_sweep_score": 20, "displacement_mss_score": 15, "pd_array_score": 15, "ob_fvg_score": 15, "volume_score": 10, "rr_score": 5, "total_score": 100
        },
        trend_15m="Bullish" if direction.upper() == "LONG" else "Bearish",
        sweep_confirmed=True,
        sweep_details="Simulated institutional liquidity sweep (BSL/SSL Purge)",
        bos_confirmed=True,
        bos_details="Simulated institutional displacement MSS",
        volume_confirmed=True,
        volume_details="RVOL 1.85 (Heavy Institutional Volume)",
        atr=round(risk * 0.8, decimals),
        reasons=[
            "💎 GRADE: 100/100 INSTITUTIONAL SNIPER (PERFECT CONFLUENCE)" if model_id == "MODEL_10" else "🌟 GRADE: A+ (INSTITUTIONAL CONVICTION)",
            f"Model: {m_name}",
            f"Coin: {symbol}",
            "4H Macro: Bullish (Institutional Bias)",
            "1H Trend: Bullish (Market Structure Shift)",
            "Dealing Range: DISCOUNT (22.5% Optimal Trade Entry)",
            "Institutional Displacement: Confirmed (Body: 84%, Exp: 1.6x)",
            "Order Block + FVG: Unmitigated Confluence Confirmed",
            "Confirmations: 7/7 (PERFECT)" if model_id == "MODEL_10" else "Confirmations: 5/7 (STRONG)",
            f"Setup Score: {'100/100 (PERFECT)' if model_id == 'MODEL_10' else '88/100'}"
        ]
    )

    setup_dict = setup.model_dump()
    setup_dict["model_id"] = model_id
    setup_dict["model_name"] = m_name
    setup_dict["confirmations_count"] = 7 if model_id == "MODEL_10" else 5
    setup_dict["grade"] = "A+"
    setup_dict["grade_badge"] = "💎 GRADE: 100/100 INSTITUTIONAL SNIPER (PERFECT CONFLUENCE)" if model_id == "MODEL_10" else "🌟 GRADE: A+ (INSTITUTIONAL CONVICTION)"
    setup_dict["pd_zone"] = "DISCOUNT" if direction.upper() == "LONG" else "PREMIUM"

    await trade_manager.process_candidates([setup])
    await broadcast_full_status()
    return {"status": "setup_simulated", "setup": setup_dict}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_websockets.append(ws)
    try:
        await ws.send_text(json.dumps({
            "type": "INITIAL_STATE",
            "data": get_system_status()
        }))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        if ws in connected_websockets:
            connected_websockets.remove(ws)
    except Exception:
        if ws in connected_websockets:
            connected_websockets.remove(ws)
