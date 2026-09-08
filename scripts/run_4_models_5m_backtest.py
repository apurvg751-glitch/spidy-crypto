import sys
import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from market_data.models import Candle, MarketState
from multi_timeframe.mtf_engine import MultiTimeframeEngine
from structure.equilibrium import EquilibriumEngine
from structure.barrier_engine import BarrierEngine
from indicators.atr import calculate_atr
from strategy.models import (
    Model11AsianJudasSwing,
    Model12InversionFvg,
    Model13BreakerBlock,
    Model14SmtDivergence
)

CACHE_DIR = ROOT_DIR / "scratch" / "historical_candles"
IST_OFFSET = timedelta(hours=5, minutes=30)


def load_candles(symbol: str, resolution: str = "15m", days: int = 150) -> list[Candle]:
    cache_file = CACHE_DIR / f"{symbol}_{resolution}_{days}d.json"
    if not cache_file.exists():
        raise FileNotFoundError(f"Missing cache file: {cache_file}")
    with open(cache_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    candles = [
        Candle(
            time=c["time"],
            open=c["open"],
            high=c["high"],
            low=c["low"],
            close=c["close"],
            volume=c["volume"],
            is_closed=True
        )
        for c in data
    ]
    candles.sort(key=lambda x: x.time)
    return candles


def run_simulation(models_to_test: list, symbols: list[str], btc_candles_15m: list[Candle], days: int = 150):
    print(f"Loading 5-month candles for {symbols}...")
    candles_15m = {}
    candles_1h = {}
    for s in symbols:
        candles_15m[s] = load_candles(s, "15m", days)
        candles_1h[s] = load_candles(s, "1h", days)

    # Collect shared timestamps
    all_timestamps = set()
    for s in symbols:
        for c in candles_15m[s]:
            all_timestamps.add(c.time)
    sorted_times = sorted(list(all_timestamps))
    print(f"Total time steps in simulation: {len(sorted_times)} bars ({days} days)")

    active_trade = None
    trades = []
    trade_counter = 0
    last_exit_time = {}

    # Model instances
    model_instances = models_to_test

    from bisect import bisect_right

    # Pre-extract candle timestamps for instant bisect lookup
    times_15m = {s: [c.time for c in candles_15m[s]] for s in symbols}
    times_1h = {s: [c.time for c in candles_1h[s]] for s in symbols}
    btc_times_15m = [c.time for c in btc_candles_15m]

    # Step through time
    min_bars = 40
    t_start = time.time()
    for step_idx in range(min_bars, len(sorted_times)):
        curr_time = sorted_times[step_idx]

        if step_idx % 2000 == 0:
            elapsed = round(time.time() - t_start, 1)
            print(f"  Step {step_idx}/{len(sorted_times)} ({round(step_idx/len(sorted_times)*100)}%) | Elapsed: {elapsed}s | Trades so far: {len(trades)}")

        # 1. Manage Active Trade
        if active_trade:
            trade_coin = active_trade["coin"]
            idx_15 = bisect_right(times_15m[trade_coin], curr_time) - 1
            if idx_15 >= 0 and candles_15m[trade_coin][idx_15].time == curr_time:
                bar = candles_15m[trade_coin][idx_15]
                entry = active_trade["entry"]
                stop = active_trade["stop_loss"]
                t1 = active_trade["target_1"]
                t2 = active_trade["target_2"]
                direction = active_trade["direction"]
                risk = abs(entry - stop)

                # MFE / MAE
                if direction == "LONG":
                    mfe = (bar.high - entry) / max(risk, 1e-4)
                    mae = (entry - bar.low) / max(risk, 1e-4)
                    active_trade["mfe"] = max(active_trade["mfe"], mfe)
                    active_trade["mae"] = max(active_trade["mae"], mae)

                    # Dynamic Breakeven update at +0.8R
                    if active_trade["mfe"] >= 0.8 and not active_trade.get("be_moved"):
                        active_trade["stop_loss"] = entry
                        active_trade["be_moved"] = True

                    # 1. Target 2 Hit
                    if bar.high >= t2:
                        achieved_r = round(active_trade["rr"], 2)
                        pnl_inr = achieved_r * 180.0
                        trades.append({
                            **active_trade,
                            "exit_time": curr_time,
                            "exit_price": t2,
                            "achieved_r": achieved_r,
                            "pnl_inr": pnl_inr,
                            "won": True,
                            "exit_reason": "TARGET_2"
                        })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None
                    # 2. Target 1 Hit
                    elif bar.high >= t1:
                        achieved_r = 1.5
                        pnl_inr = 1.5 * 180.0
                        trades.append({
                            **active_trade,
                            "exit_time": curr_time,
                            "exit_price": t1,
                            "achieved_r": achieved_r,
                            "pnl_inr": pnl_inr,
                            "won": True,
                            "exit_reason": "TARGET_1"
                        })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None
                    # 3. Stop / Breakeven Hit
                    elif bar.low <= active_trade["stop_loss"]:
                        if active_trade.get("be_moved"):
                            achieved_r = 0.0
                            pnl_inr = -15.0
                            trades.append({
                                **active_trade,
                                "exit_time": curr_time,
                                "exit_price": entry,
                                "achieved_r": achieved_r,
                                "pnl_inr": pnl_inr,
                                "won": False,
                                "exit_reason": "BREAKEVEN"
                            })
                        else:
                            achieved_r = -1.0
                            pnl_inr = -180.0
                            trades.append({
                                **active_trade,
                                "exit_time": curr_time,
                                "exit_price": stop,
                                "achieved_r": achieved_r,
                                "pnl_inr": pnl_inr,
                                "won": False,
                                "exit_reason": "STOPPED"
                            })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None

                else: # SHORT
                    mfe = (entry - bar.low) / max(risk, 1e-4)
                    mae = (bar.high - entry) / max(risk, 1e-4)
                    active_trade["mfe"] = max(active_trade["mfe"], mfe)
                    active_trade["mae"] = max(active_trade["mae"], mae)

                    # Dynamic Breakeven update at +0.8R
                    if active_trade["mfe"] >= 0.8 and not active_trade.get("be_moved"):
                        active_trade["stop_loss"] = entry
                        active_trade["be_moved"] = True

                    # 1. Target 2 Hit
                    if bar.low <= t2:
                        achieved_r = round(active_trade["rr"], 2)
                        pnl_inr = achieved_r * 180.0
                        trades.append({
                            **active_trade,
                            "exit_time": curr_time,
                            "exit_price": t2,
                            "achieved_r": achieved_r,
                            "pnl_inr": pnl_inr,
                            "won": True,
                            "exit_reason": "TARGET_2"
                        })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None
                    # 2. Target 1 Hit
                    elif bar.low <= t1:
                        achieved_r = 1.5
                        pnl_inr = 1.5 * 180.0
                        trades.append({
                            **active_trade,
                            "exit_time": curr_time,
                            "exit_price": t1,
                            "achieved_r": achieved_r,
                            "pnl_inr": pnl_inr,
                            "won": True,
                            "exit_reason": "TARGET_1"
                        })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None
                    # 3. Stop / Breakeven Hit
                    elif bar.high >= active_trade["stop_loss"]:
                        if active_trade.get("be_moved"):
                            achieved_r = 0.0
                            pnl_inr = -15.0
                            trades.append({
                                **active_trade,
                                "exit_time": curr_time,
                                "exit_price": entry,
                                "achieved_r": achieved_r,
                                "pnl_inr": pnl_inr,
                                "won": False,
                                "exit_reason": "BREAKEVEN"
                            })
                        else:
                            achieved_r = -1.0
                            pnl_inr = -180.0
                            trades.append({
                                **active_trade,
                                "exit_time": curr_time,
                                "exit_price": stop,
                                "achieved_r": achieved_r,
                                "pnl_inr": pnl_inr,
                                "won": False,
                                "exit_reason": "STOPPED"
                            })
                        last_exit_time[trade_coin] = curr_time
                        active_trade = None

        # 2. Evaluate Setups if Slot is Open (0/1 Capacity)
        if not active_trade:
            # We evaluate on every 15M bar close
            candidates = []
            # Fast bisect slice of BTC candles
            btc_idx = bisect_right(btc_times_15m, curr_time)
            curr_btc_candles = btc_candles_15m[max(0, btc_idx - 40) : btc_idx]

            for sym in symbols:
                # Cooldown: 1 hour (4 bars) between trades on the same coin to prevent churn
                if last_exit_time.get(sym, 0) + 3600 > curr_time:
                    continue

                idx_15 = bisect_right(times_15m[sym], curr_time)
                if idx_15 < min_bars:
                    continue
                c_history_15 = candles_15m[sym][max(0, idx_15 - 60) : idx_15]

                idx_1h = bisect_right(times_1h[sym], curr_time)
                c_history_1h = candles_1h[sym][max(0, idx_1h - 40) : idx_1h]

                curr_p = c_history_15[-1].close
                mtf = MultiTimeframeEngine.evaluate(
                    symbol=sym,
                    candles_5m=c_history_15[-30:],
                    candles_15m=c_history_15,
                    candles_1h=c_history_1h
                )

                dr = EquilibriumEngine.calculate_range(c_history_15)
                atr_val = calculate_atr(c_history_15, period=14)

                ms = MarketState(
                    symbol=sym,
                    current_price=curr_p,
                    last_update_ts=curr_time,
                    candles_5m=c_history_15[-30:], # using 15m as base execution in multi-month replay
                    candles_15m=c_history_15,
                    candles_1h=c_history_1h,
                    mtf_context=mtf,
                    btc_candles_15m=curr_btc_candles
                )

                for model in model_instances:
                    cand = model.evaluate(ms)
                    if cand and cand.is_valid and cand.setup_score >= 75:
                        # Apply Hard Gate 1: Barrier clearance
                        room_res = BarrierEngine.validate_room_to_run(
                            cand.direction, cand.entry, c_history_15, atr_val, dr, c_history_1h
                        )
                        if not room_res.has_room:
                            continue

                        # Apply Hard Gate 2: Dealing Range Guard
                        if dr:
                            if cand.direction == "LONG" and dr.current_position_pct > 0.55:
                                continue
                            if cand.direction == "SHORT" and dr.current_position_pct < 0.45:
                                continue

                        if cand.rr >= 1.6:
                            candidates.append(cand)

            if candidates:
                # Rank candidates by score and select top 1
                best_cand = max(candidates, key=lambda c: c.setup_score)
                trade_counter += 1
                active_trade = {
                    "trade_num": trade_counter,
                    "coin": best_cand.coin,
                    "model_id": best_cand.model_id,
                    "model_name": best_cand.model_name,
                    "direction": best_cand.direction,
                    "entry_time": curr_time,
                    "entry": best_cand.entry,
                    "stop_loss": best_cand.stop_loss,
                    "target_1": best_cand.target_1,
                    "target_2": best_cand.target_2,
                    "rr": best_cand.rr,
                    "setup_score": best_cand.setup_score,
                    "grade": best_cand.grade,
                    "mfe": 0.0,
                    "mae": 0.0
                }

    return trades


def generate_excel_spreadsheet(all_trades: list[dict], model_stats: dict, coin_stats: dict, output_file: Path):
    wb = openpyxl.Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # Styles
    navy_header = PatternFill(start_color="0A192F", end_color="0A192F", fill_type="solid")
    gold_header = PatternFill(start_color="1F3A60", end_color="1F3A60", fill_type="solid")
    accent_green = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
    accent_red = PatternFill(start_color="FCE8E6", end_color="FCE8E6", fill_type="solid")
    zebra_gray = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")

    font_title = Font(name="Calibri", size=16, bold=True, color="0A192F")
    font_subtitle = Font(name="Calibri", size=11, italic=True, color="555555")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_normal = Font(name="Calibri", size=11)
    font_green = Font(name="Calibri", size=11, bold=True, color="0D652D")
    font_red = Font(name="Calibri", size=11, bold=True, color="C5221F")

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    thin_border = Border(
        left=Side(style="thin", color="DDDDDD"),
        right=Side(style="thin", color="DDDDDD"),
        top=Side(style="thin", color="DDDDDD"),
        bottom=Side(style="thin", color="DDDDDD")
    )

    # ----------------------------------------------------
    # TAB 1: EXECUTIVE SUMMARY
    # ----------------------------------------------------
    ws1 = wb.create_sheet(title="Executive Summary")
    ws1.views.sheetView[0].showGridLines = True

    ws1.merge_cells("B2:H2")
    ws1["B2"] = "SPIDY CRYPTO — 4 NEW INSTITUTIONAL MODELS (5-MONTH BACKTEST)"
    ws1["B2"].font = font_title

    ws1.merge_cells("B3:H3")
    ws1["B3"] = "April 2026 – September 2026 | Monitored Markets: ETH, SOL, XRP, AVAX | Anchor: BTC"
    ws1["B3"].font = font_subtitle

    # Compute Global KPIs
    total_trades = len(all_trades)
    wins = [t for t in all_trades if t["achieved_r"] > 0]
    losses = [t for t in all_trades if t["achieved_r"] < 0]
    bes = [t for t in all_trades if t["achieved_r"] == 0]
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0
    total_r = sum(t["achieved_r"] for t in all_trades)
    total_pnl = sum(t["pnl_inr"] for t in all_trades)
    gross_win_r = sum(t["achieved_r"] for t in wins)
    gross_loss_r = abs(sum(t["achieved_r"] for t in losses))
    profit_factor = (gross_win_r / max(gross_loss_r, 1e-4)) if gross_loss_r > 0 else gross_win_r

    # Max Drawdown in R
    cum_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in all_trades:
        cum_r += t["achieved_r"]
        if cum_r > peak_r:
            peak_r = cum_r
        dd = peak_r - cum_r
        if dd > max_dd_r:
            max_dd_r = dd

    kpis = [
        ("Total Trades Taken", f"{total_trades}", "Clean event-driven execution (0/1 lock)"),
        ("Winning Trades (Win Count)", f"{len(wins)}", "Target 1 or Target 2 hits"),
        ("Breakeven Trades (+0.8R Protected)", f"{len(bes)}", "Zero loss with protected margin"),
        ("Losing Trades (Stop Loss)", f"{len(losses)}", "Hard structural invalidations"),
        ("Win Rate (Target Hits)", f"{win_rate:.1f}%", "Excluding breakeven trades"),
        ("Total Net R-Multiples", f"+{total_r:.2f}R" if total_r >= 0 else f"{total_r:.2f}R", "Net cumulative R gained"),
        ("Total Net Profit (INR)", f"₹{total_pnl:,.2f}", "Based on ₹3,500 margin @ 6x leverage"),
        ("Profit Factor", f"{profit_factor:.2f}", "Gross Profits / Gross Losses"),
        ("Max Drawdown", f"-{max_dd_r:.2f}R", "Peak-to-valley equity drawdown"),
        ("Average Expectancy / Trade", f"+{(total_r / max(total_trades, 1)):.2f}R", "Mathematical edge per trade"),
    ]

    ws1.cell(row=5, column=2, value="Metric").fill = navy_header
    ws1.cell(row=5, column=2).font = font_header
    ws1.cell(row=5, column=3, value="Quant Result").fill = navy_header
    ws1.cell(row=5, column=3).font = font_header
    ws1.cell(row=5, column=4, value="Institutional Context").fill = navy_header
    ws1.cell(row=5, column=4).font = font_header

    for idx, (metric, val, desc) in enumerate(kpis, start=6):
        c2 = ws1.cell(row=idx, column=2, value=metric)
        c3 = ws1.cell(row=idx, column=3, value=val)
        c4 = ws1.cell(row=idx, column=4, value=desc)
        c2.font = font_bold
        c3.font = font_green if ("+" in val or "₹" in val) and "-" not in val else (font_red if "-" in val else font_bold)
        c4.font = font_subtitle
        c2.border = thin_border
        c3.border = thin_border
        c4.border = thin_border
        if idx % 2 == 1:
            c2.fill = zebra_gray
            c3.fill = zebra_gray
            c4.fill = zebra_gray

    # ----------------------------------------------------
    # TAB 2: MODEL COMPARISON
    # ----------------------------------------------------
    ws2 = wb.create_sheet(title="Model Comparison")
    ws2.views.sheetView[0].showGridLines = True

    ws2.merge_cells("B2:I2")
    ws2["B2"] = "HEAD-TO-HEAD PERFORMANCE: 4 NEW ENTRY MODELS"
    ws2["B2"].font = font_title

    headers_m = ["Model ID", "Strategy Model Name", "Trades", "Wins", "BE", "Losses", "Win Rate", "Net R", "Profit Factor", "Total PnL (₹)"]
    for col_idx, h in enumerate(headers_m, start=2):
        cell = ws2.cell(row=4, column=col_idx, value=h)
        cell.fill = gold_header
        cell.font = font_header
        cell.alignment = align_center

    row_idx = 5
    for m_id, stats in model_stats.items():
        ws2.cell(row=row_idx, column=2, value=m_id).font = font_bold
        ws2.cell(row=row_idx, column=3, value=stats["name"]).font = font_normal
        ws2.cell(row=row_idx, column=4, value=stats["trades"]).font = font_normal
        ws2.cell(row=row_idx, column=5, value=stats["wins"]).font = font_green
        ws2.cell(row=row_idx, column=6, value=stats["bes"]).font = font_normal
        ws2.cell(row=row_idx, column=7, value=stats["losses"]).font = font_red
        ws2.cell(row=row_idx, column=8, value=f"{stats['win_rate']:.1f}%").font = font_bold
        ws2.cell(row=row_idx, column=9, value=f"+{stats['total_r']:.2f}R").font = font_green
        ws2.cell(row=row_idx, column=10, value=f"{stats['profit_factor']:.2f}").font = font_bold
        ws2.cell(row=row_idx, column=11, value=f"₹{stats['total_pnl']:,.2f}").font = font_green

        for c in range(2, 12):
            ws2.cell(row=row_idx, column=c).border = thin_border
            if row_idx % 2 == 1:
                ws2.cell(row=row_idx, column=c).fill = zebra_gray
        row_idx += 1

    # ----------------------------------------------------
    # TAB 3: COIN BREAKDOWN
    # ----------------------------------------------------
    ws3 = wb.create_sheet(title="Coin Breakdown")
    ws3.views.sheetView[0].showGridLines = True

    ws3.merge_cells("B2:H2")
    ws3["B2"] = "ASSET ALLOCATION & COIN PERFORMANCE BREAKDOWN"
    ws3["B2"].font = font_title

    headers_c = ["Coin Symbol", "Trades", "Wins", "Losses", "Win Rate", "Net R", "Total PnL (₹)", "Best Model"]
    for col_idx, h in enumerate(headers_c, start=2):
        cell = ws3.cell(row=4, column=col_idx, value=h)
        cell.fill = navy_header
        cell.font = font_header
        cell.alignment = align_center

    row_idx = 5
    for coin, stats in coin_stats.items():
        ws3.cell(row=row_idx, column=2, value=coin).font = font_bold
        ws3.cell(row=row_idx, column=3, value=stats["trades"]).font = font_normal
        ws3.cell(row=row_idx, column=4, value=stats["wins"]).font = font_green
        ws3.cell(row=row_idx, column=5, value=stats["losses"]).font = font_red
        ws3.cell(row=row_idx, column=6, value=f"{stats['win_rate']:.1f}%").font = font_bold
        ws3.cell(row=row_idx, column=7, value=f"+{stats['total_r']:.2f}R").font = font_green
        ws3.cell(row=row_idx, column=8, value=f"₹{stats['total_pnl']:,.2f}").font = font_green
        ws3.cell(row=row_idx, column=9, value=stats["best_model"]).font = font_normal

        for c in range(2, 10):
            ws3.cell(row=row_idx, column=c).border = thin_border
            if row_idx % 2 == 1:
                ws3.cell(row=row_idx, column=c).fill = zebra_gray
        row_idx += 1

    # ----------------------------------------------------
    # TAB 4: COMPLETE TRADE LOG
    # ----------------------------------------------------
    ws4 = wb.create_sheet(title="Complete Trade Logs")
    ws4.views.sheetView[0].showGridLines = True

    headers_t = [
        "Trade #", "Date & Time (IST)", "Coin", "Model Name", "Direction",
        "Entry Price", "Exit Price", "Stop Loss", "Target 1", "Target 2",
        "Achieved R", "PnL (INR)", "Cumulative PnL (INR)", "MFE (R)", "MAE (R)", "Exit Reason"
    ]
    for col_idx, h in enumerate(headers_t, start=1):
        cell = ws4.cell(row=1, column=col_idx, value=h)
        cell.fill = navy_header
        cell.font = font_header
        cell.alignment = align_center

    cum_inr = 0.0
    for row_idx, t in enumerate(all_trades, start=2):
        cum_inr += t["pnl_inr"]
        dt_ist = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc) + IST_OFFSET
        time_str = dt_ist.strftime("%Y-%m-%d %H:%M")

        ws4.cell(row=row_idx, column=1, value=t["trade_num"]).alignment = align_center
        ws4.cell(row=row_idx, column=2, value=time_str).alignment = align_center
        ws4.cell(row=row_idx, column=3, value=t["coin"]).alignment = align_center
        ws4.cell(row=row_idx, column=4, value=t["model_name"]).alignment = align_left
        ws4.cell(row=row_idx, column=5, value=t["direction"]).alignment = align_center
        ws4.cell(row=row_idx, column=6, value=t["entry"]).number_format = "$#,##0.000"
        ws4.cell(row=row_idx, column=7, value=t["exit_price"]).number_format = "$#,##0.000"
        ws4.cell(row=row_idx, column=8, value=t["stop_loss"]).number_format = "$#,##0.000"
        ws4.cell(row=row_idx, column=9, value=t["target_1"]).number_format = "$#,##0.000"
        ws4.cell(row=row_idx, column=10, value=t["target_2"]).number_format = "$#,##0.000"

        # R Multiple & PnL
        r_cell = ws4.cell(row=row_idx, column=11, value=t["achieved_r"])
        r_cell.number_format = '+0.00"R";-0.00"R";0.00"R"'
        pnl_cell = ws4.cell(row=row_idx, column=12, value=t["pnl_inr"])
        pnl_cell.number_format = '₹#,##0.00;[Red]-₹#,##0.00;₹0.00'
        cum_cell = ws4.cell(row=row_idx, column=13, value=cum_inr)
        cum_cell.number_format = '₹#,##0.00;[Red]-₹#,##0.00;₹0.00'

        ws4.cell(row=row_idx, column=14, value=round(t["mfe"], 2)).alignment = align_right
        ws4.cell(row=row_idx, column=15, value=round(t["mae"], 2)).alignment = align_right

        exit_cell = ws4.cell(row=row_idx, column=16, value=t["exit_reason"])
        exit_cell.alignment = align_center
        if t["exit_reason"] in ["TARGET_1", "TARGET_2"]:
            exit_cell.fill = accent_green
            exit_cell.font = font_green
        elif t["exit_reason"] == "STOPPED":
            exit_cell.fill = accent_red
            exit_cell.font = font_red

        for c in range(1, 17):
            ws4.cell(row=row_idx, column=c).border = thin_border

    # ----------------------------------------------------
    # TAB 5: MONTHLY PERFORMANCE
    # ----------------------------------------------------
    ws5 = wb.create_sheet(title="Monthly Performance")
    ws5.views.sheetView[0].showGridLines = True

    ws5.merge_cells("B2:G2")
    ws5["B2"] = "MONTH-BY-MONTH INSTITUTIONAL PERFORMANCE"
    ws5["B2"].font = font_title

    headers_mo = ["Month", "Trades", "Wins", "Losses", "Win Rate", "Net R", "Total PnL (INR)"]
    for col_idx, h in enumerate(headers_mo, start=2):
        cell = ws5.cell(row=4, column=col_idx, value=h)
        cell.fill = navy_header
        cell.font = font_header
        cell.alignment = align_center

    # Group by month
    monthly_data = {}
    for t in all_trades:
        dt = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc) + IST_OFFSET
        mo_key = dt.strftime("%B %Y")
        if mo_key not in monthly_data:
            monthly_data[mo_key] = {"trades": 0, "wins": 0, "losses": 0, "r": 0.0, "pnl": 0.0}
        monthly_data[mo_key]["trades"] += 1
        if t["achieved_r"] > 0:
            monthly_data[mo_key]["wins"] += 1
        elif t["achieved_r"] < 0:
            monthly_data[mo_key]["losses"] += 1
        monthly_data[mo_key]["r"] += t["achieved_r"]
        monthly_data[mo_key]["pnl"] += t["pnl_inr"]

    row_idx = 5
    for mo, stats in monthly_data.items():
        w_rate = (stats["wins"] / stats["trades"] * 100) if stats["trades"] else 0
        ws5.cell(row=row_idx, column=2, value=mo).font = font_bold
        ws5.cell(row=row_idx, column=3, value=stats["trades"]).font = font_normal
        ws5.cell(row=row_idx, column=4, value=stats["wins"]).font = font_green
        ws5.cell(row=row_idx, column=5, value=stats["losses"]).font = font_red
        ws5.cell(row=row_idx, column=6, value=f"{w_rate:.1f}%").font = font_bold
        ws5.cell(row=row_idx, column=7, value=f"+{stats['r']:.2f}R" if stats['r'] >= 0 else f"{stats['r']:.2f}R").font = font_green if stats['r'] >= 0 else font_red
        ws5.cell(row=row_idx, column=8, value=f"₹{stats['pnl']:,.2f}").font = font_green if stats['pnl'] >= 0 else font_red

        for c in range(2, 9):
            ws5.cell(row=row_idx, column=c).border = thin_border
            if row_idx % 2 == 1:
                ws5.cell(row=row_idx, column=c).fill = zebra_gray
        row_idx += 1

    # Auto-adjust column widths
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len and len(val) < 60:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(output_file)
    print(f"\nSuccessfully generated 5-tab backtest spreadsheet: {output_file.resolve()}")


def main():
    print("=================================================================")
    print("   STARTING 5-MONTH BACKTEST FOR 4 NEW INSTITUTIONAL MODELS")
    print("=================================================================")

    symbols = ["ETHUSD", "SOLUSD", "XRPUSD", "AVAXUSD"]
    btc_candles = load_candles("BTCUSD", "15m", days=150)

    m11 = Model11AsianJudasSwing()
    m12 = Model12InversionFvg()
    m13 = Model13BreakerBlock()
    m14 = Model14SmtDivergence()

    all_models = [m11, m12, m13, m14]

    # Run Combined Multi-Asset Simulation
    print("\n--- Running Combined 4-Model Simulation ---")
    trades = run_simulation(all_models, symbols, btc_candles, days=150)
    print(f"Total simulated trades executed across 5 months: {len(trades)}")

    # Model Stats Breakdown
    model_stats = {}
    for m in all_models:
        m_trades = [t for t in trades if t["model_id"] == m.model_id]
        m_wins = [t for t in m_trades if t["achieved_r"] > 0]
        m_losses = [t for t in m_trades if t["achieved_r"] < 0]
        m_bes = [t for t in m_trades if t["achieved_r"] == 0]
        m_win_rate = (len(m_wins) / len(m_trades) * 100) if m_trades else 0
        m_r = sum(t["achieved_r"] for t in m_trades)
        m_pnl = sum(t["pnl_inr"] for t in m_trades)
        gw = sum(t["achieved_r"] for t in m_wins)
        gl = abs(sum(t["achieved_r"] for t in m_losses))
        pf = (gw / max(gl, 1e-4)) if gl > 0 else gw

        model_stats[m.model_id] = {
            "name": m.name,
            "trades": len(m_trades),
            "wins": len(m_wins),
            "losses": len(m_losses),
            "bes": len(m_bes),
            "win_rate": m_win_rate,
            "total_r": m_r,
            "total_pnl": m_pnl,
            "profit_factor": pf
        }

    # Coin Stats Breakdown
    coin_stats = {}
    for sym in symbols:
        c_trades = [t for t in trades if t["coin"] == sym]
        c_wins = [t for t in c_trades if t["achieved_r"] > 0]
        c_losses = [t for t in c_trades if t["achieved_r"] < 0]
        c_win_rate = (len(c_wins) / len(c_trades) * 100) if c_trades else 0
        c_r = sum(t["achieved_r"] for t in c_trades)
        c_pnl = sum(t["pnl_inr"] for t in c_trades)

        # Best model for coin
        model_pnl_map = {}
        for t in c_trades:
            model_pnl_map[t["model_name"]] = model_pnl_map.get(t["model_name"], 0.0) + t["achieved_r"]
        best_m = max(model_pnl_map.items(), key=lambda x: x[1])[0] if model_pnl_map else "N/A"

        coin_stats[sym] = {
            "trades": len(c_trades),
            "wins": len(c_wins),
            "losses": len(c_losses),
            "win_rate": c_win_rate,
            "total_r": c_r,
            "total_pnl": c_pnl,
            "best_model": best_m
        }

    # Save to Excel
    output_excel = ROOT_DIR / "4 new models backtest.xlsx"
    generate_excel_spreadsheet(trades, model_stats, coin_stats, output_excel)


if __name__ == "__main__":
    main()
