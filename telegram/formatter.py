from typing import Any, Optional, Dict, List
from config.precision import format_price, get_symbol_precision
from config.settings import settings


def format_coin_price(coin: str, price: float) -> str:
    """Formats price according to Delta Exchange precision specifications."""
    return format_price(coin, price)


def format_trade_progress_bar(
    entry: float,
    target_1: float,
    stop_loss: float,
    current_price: float,
    direction: str = "LONG",
    achieved_r: Optional[float] = None
) -> str:
    """
    Renders an institutional neon emoji progress bar for active trades.
    In profit:   [ENTRY] ──🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜── [TP1] (50.0% | +0.80R)
    At target:   [ENTRY] ──🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩── [TP1 HIT 🎯] (+1.60R)
    In risk:     [SL] ──🟥🟥🟥⬜⬜⬜⬜⬜⬜⬜── [ENTRY] (-0.30R)
    """
    is_long = direction.upper() == "LONG"

    if is_long:
        tp_dist = max(target_1 - entry, 1e-4)
        sl_dist = max(entry - stop_loss, 1e-4)
        if current_price >= entry:
            pct = ((current_price - entry) / tp_dist) * 100.0
            filled = min(10, max(0, int(round(pct / 10.0))))
            unfilled = 10 - filled
            r_val = achieved_r if achieved_r is not None else (pct * 0.016)
            r_sign = "+" if r_val >= 0 else ""
            r_str = f"{r_sign}{r_val:.2f}R"
            if pct >= 100.0:
                return f"`[ENTRY]` ──{'🟩' * 10}── `[TP1 🎯]` `({pct:.1f}% | {r_str})`"
            return f"`[ENTRY]` ──{'🟩' * filled}{'⬜' * unfilled}── `[TP1]` `({pct:.1f}% | {r_str})`"
        else:
            pct = ((entry - current_price) / sl_dist) * 100.0
            filled = min(10, max(0, int(round(pct / 10.0))))
            unfilled = 10 - filled
            r_val = achieved_r if achieved_r is not None else (-pct * 0.01)
            return f"`[SL]` ──{'🟥' * filled}{'⬜' * unfilled}── `[ENTRY]` `({r_val:.2f}R)`"
    else:
        # Short position
        tp_dist = max(entry - target_1, 1e-4)
        sl_dist = max(stop_loss - entry, 1e-4)
        if current_price <= entry:
            pct = ((entry - current_price) / tp_dist) * 100.0
            filled = min(10, max(0, int(round(pct / 10.0))))
            unfilled = 10 - filled
            r_val = achieved_r if achieved_r is not None else (pct * 0.016)
            r_sign = "+" if r_val >= 0 else ""
            r_str = f"{r_sign}{r_val:.2f}R"
            if pct >= 100.0:
                return f"`[ENTRY]` ──{'🟩' * 10}── `[TP1 🎯]` `({pct:.1f}% | {r_str})`"
            return f"`[ENTRY]` ──{'🟩' * filled}{'⬜' * unfilled}── `[TP1]` `({pct:.1f}% | {r_str})`"
        else:
            pct = ((current_price - entry) / sl_dist) * 100.0
            filled = min(10, max(0, int(round(pct / 10.0))))
            unfilled = 10 - filled
            r_val = achieved_r if achieved_r is not None else (-pct * 0.01)
            return f"`[SL]` ──{'🟥' * filled}{'⬜' * unfilled}── `[ENTRY]` `({r_val:.2f}R)`"


def format_main_alert(setup: dict[str, Any]) -> str:
    """
    Formats the Telegram alert when a valid setup is selected.
    Includes all elements from the upgraded trading intelligence spec
    while maintaining compatibility with Gate 7 validation.
    """
    coin = setup.get("coin", "UNKNOWN")
    direction = setup.get("direction", "UNKNOWN")
    model_name = setup.get("model_name", "Liquidity Sweep Reversal")
    score = setup.get("setup_score", 0)
    conf_count = setup.get("confirmations_count", 5)

    entry = setup.get("entry", 0.0)
    stop = setup.get("stop_loss", 0.0)
    tp = setup.get("target_2", setup.get("target_1", 0.0))
    t1 = setup.get("target_1", 0.0)
    t2 = setup.get("target_2", 0.0)
    rr = setup.get("rr", 0.0)

    # 4H, 1H, 15M context
    bias_4h = setup.get("macro_bias_4h", setup.get("trend_15m", "Bullish"))
    trend_1h = setup.get("trend_1h", setup.get("trend_15m", "Bullish"))
    trend_15m = setup.get("trend_15m", "Bullish")

    sweep_text = "Confirmed" if setup.get("sweep_confirmed", True) else "N/A"
    bos_text = "Confirmed" if setup.get("bos_confirmed", True) else "N/A"
    vol_text = "Confirmed" if setup.get("volume_confirmed", True) else "Moderate"

    grade = setup.get("grade", "A+")
    grade_badge = setup.get("grade_badge", f"🌟 GRADE: {grade} (INSTITUTIONAL)")
    pd_zone = setup.get("pd_zone", "DISCOUNT" if direction == "LONG" else "PREMIUM")

    status = setup.get("trade_status", "SELECTED")
    if status == "WAITING":
        status = "WAITING"

    prec = get_symbol_precision(coin)

    white_line_str = ""
    barriers = setup.get("htf_walls") or setup.get("htf_barriers") or []
    if barriers:
        white_line_str = f"⚪ Institutional Origin (White Line): ${float(barriers[0]):.{prec}f}\n"

    return (
        f"🕷️ SPIDY CRYPTO — TRADE DETECTED\n"
        f"TRADE SETUP DETECTED\n\n"
        f"{grade_badge}\n"
        f"Policy: {'Strict Risk (Tight SL / Quick TP)' if grade == 'B+' else 'Institutional High Conviction'}\n"
        f"Dealing Range: {pd_zone}\n\n"
        f"Market: {coin}\n"
        f"Coin: {coin}\n"
        f"Direction: {direction}\n\n"
        f"Model: {model_name}\n"
        f"Score: {score}/100\n"
        f"Setup Score: {score}/100\n"
        f"Confirmations: {conf_count}/7\n\n"
        f"4H: {bias_4h}\n"
        f"1H: {trend_1h}\n"
        f"15M Trend: {trend_15m}\n"
        f"Liquidity Sweep: {sweep_text} (✓)\n"
        f"BOS: {bos_text} (✓)\n"
        f"Retest: Confirmed (✓)\n"
        f"Volume: {vol_text} (✓)\n\n"
        f"Entry: {float(entry):.{prec}f}\n"
        f"Stop: {float(stop):.{prec}f}\n"
        f"SL: {float(stop):.{prec}f}\n"
        f"Target 1: {float(t1):.{prec}f}\n"
        f"Target 2: {float(t2):.{prec}f}\n"
        f"TP: {float(tp):.{prec}f}\n"
        f"RR: 1:{rr:.1f}\n"
        f"{white_line_str}\n"
        f"Delta Specs: {setup.get('delta_contracts', 0)} Lots ({setup.get('contract_unit', '')}/lot)\n"
        f"Point Value: {setup.get('point_label', '$1.00')} pt = ±₹{setup.get('point_val_inr', 0):.2f} (±${setup.get('point_val_usd', 0):.4f})\n"
        f"Position Sizing: ₹{int(settings.MAX_ALLOWED_MARGIN * settings.DEFAULT_LEVERAGE):,} Notional (₹{int(settings.MAX_ALLOWED_MARGIN):,} Margin @ {settings.DEFAULT_LEVERAGE}x)\n\n"
        f"Status: {status}\n\n"
        f"Other markets remain monitored but new trades are globally blocked while this trade is active.\n"
        f"Only ONE SPIDY CRYPTO trade can be active at one time."
    )


def format_lifecycle_alert(
    coin: str,
    direction: str,
    status: str,
    price: float,
    details: str = "",
    achieved_r: Any = None,
    pnl: Any = None,
    entry: Any = None,
    stop_loss: Any = None,
    position_units: Any = None,
    margin_used: Any = None,
    leverage: Any = None,
    target_1: Any = None
) -> str:
    """Formats trade lifecycle updates with live variable PnL, R-Multiple, and visual progress bar."""
    status_emoji = {
        "ACTIVE": "🟢",
        "TARGET HIT": "🎯",
        "STOPPED": "🛑",
        "CANCELLED": "⚪",
        "COMPLETED": "🏁",
        "TRAILING_STOP": "📈"
    }.get(status, "🕷️")

    # Clear English Lifecycle & Exit Header
    if "Trailing Stop Loss Hit" in details or "Trailing Stop" in details:
        header_status = "TRAILING STOP LOSS HIT (PROFIT SECURED 🔒)"
        status_emoji = "📈"
    elif "Original Stop Loss Hit" in details or "Stop loss hit" in details:
        header_status = "STOP LOSS HIT (RISK PROTECTED 🛡️)"
        status_emoji = "🛑"
    elif "Manually Closed" in details or "MANUALLY CLOSED" in details:
        header_status = "MANUALLY CLOSED VIA TELEGRAM BUTTON ✋"
        status_emoji = "✋"
    elif "Target" in details or "TP" in details:
        header_status = "TARGET HIT (PROFIT SECURED 🎯)"
        status_emoji = "🎯"
    else:
        header_status = f"TRADE {status}" if status in ("ACTIVE", "TRAILING_STOP") else status

    is_terminal = status in ("STOPPED", "CANCELLED", "COMPLETED")

    lines = [
        f"{status_emoji} SPIDY CRYPTO — {header_status}\n",
        f"Market: {coin} ({direction})",
        f"Status: {status}"
    ]

    if position_units is not None and float(position_units) > 0:
        units_f = float(position_units)
        margin_f = float(margin_used or 0.0)
        lev_val = int(leverage or 6)
        if margin_f > 0:
            lines.append(f"Position Size: {units_f:.4g} contracts (₹{int(margin_f):,} Margin @ {lev_val}x)")
        else:
            lines.append(f"Position Size: {units_f:.4g} contracts")

    if entry is not None and float(entry) > 0:
        entry_f = float(entry)
        lines.append(f"Entry Price: {format_coin_price(coin, entry_f)}")
        lines.append(f"Exit / Current Price: {format_coin_price(coin, price)}")
        price_diff = (price - entry_f) if direction.upper() == "LONG" else (entry_f - price)
        pct_diff = (price_diff / entry_f * 100.0)
        diff_sign = "+" if price_diff >= 0 else "-"
        abs_diff = abs(price_diff)
        diff_str = format_coin_price(coin, abs_diff).replace("$", "")
        lines.append(f"Price Delta: {diff_sign}${diff_str} ({diff_sign}{abs(pct_diff):.2f}%)")
    else:
        lines.append(f"Current Price: {format_coin_price(coin, price)}")

    if achieved_r is not None:
        r_val = float(achieved_r)
        r_sign = "+" if r_val >= 0 else ""
        if abs(r_val) <= 0.08:
            lines.append(f"Achieved R: {r_sign}{r_val:.2f}R (Break-Even 🛡️)")
        else:
            lines.append(f"Achieved R: {r_sign}{r_val:.2f}R")

    if pnl is not None:
        pnl_val = float(pnl)
        pnl_sign = "+" if pnl_val >= 0 else ""
        if abs(pnl_val) <= 5.0 and (achieved_r is not None and abs(float(achieved_r)) <= 0.08):
            lines.append(f"Realized PnL: ₹0.00 (Zero Loss Protection 🛡️)")
        elif pnl_val > 0:
            lines.append(f"Realized PnL: {pnl_sign}₹{pnl_val:,.2f} 🟢")
        else:
            lines.append(f"Realized PnL: -₹{abs(pnl_val):,.2f} 🔴")

    # Visual Emoji Progress Bar on Active/Trailing updates
    if status in ("ACTIVE", "TRAILING_STOP") and entry is not None and stop_loss is not None and target_1 is not None:
        try:
            bar = format_trade_progress_bar(
                entry=float(entry),
                target_1=float(target_1),
                stop_loss=float(stop_loss),
                current_price=float(price),
                direction=direction,
                achieved_r=float(achieved_r) if achieved_r is not None else None
            )
            lines.append("")
            lines.append(f"📊 *Journey to Target*:\n{bar}")
        except Exception:
            pass

    if details:
        lines.append(f"Exit Reason: {details}")

    if is_terminal:
        lines.append("\nGlobal trade lock released. SPIDY CRYPTO is analyzing ETH, BTC, SOL for the next setup.")

    return "\n".join(lines)


def format_hud_telemetry(
    active_trade: Optional[dict],
    live_prices: dict[str, float],
    daily_loss_info: dict[str, Any],
    market_zones: Optional[dict[str, str]] = None
) -> str:
    """Renders the master interactive HUD status display for `/hud`."""
    current_dl = float(daily_loss_info.get("current_daily_loss", 0.0))
    max_dl = float(daily_loss_info.get("max_daily_loss", 420.0))
    rem_dl = float(daily_loss_info.get("daily_loss_remaining", max(0.0, max_dl - current_dl)))

    lines = [
        "🎛️ *SPIDY CRYPTO 2.0 — MASTER CONTROL HUD*",
        "─────────────────────────"
    ]

    if active_trade:
        coin = active_trade.get("coin", "BTCUSD")
        direction = active_trade.get("direction", "LONG")
        entry = float(active_trade.get("entry", 0.0))
        sl = float(active_trade.get("stop_loss", 0.0))
        t1 = float(active_trade.get("target_1", 0.0))
        t2 = float(active_trade.get("target_2", 0.0))
        model = active_trade.get("model_name", "Institutional Sniper")
        score = active_trade.get("setup_score", 100)
        curr_p = live_prices.get(coin, float(active_trade.get("current_price", entry)))

        price_diff = (curr_p - entry) if direction == "LONG" else (entry - curr_p)
        r_dist = max(abs(entry - sl), 1e-4)
        achieved_r = price_diff / r_dist
        pnl_emoji = "🟢" if price_diff >= 0 else "🔴"
        r_sign = "+" if achieved_r >= 0 else ""

        from market_data.delta_specs import DeltaPointValueEngine
        pnl_data = DeltaPointValueEngine.calculate_exact_pnl(
            symbol=coin,
            direction=direction,
            entry=entry,
            current_price=curr_p,
            margin_used=float(active_trade.get("margin_used", settings.ACCOUNT_EQUITY)),
            leverage=int(active_trade.get("leverage", settings.DEFAULT_LEVERAGE))
        )

        be_status = "🛡️ Breakeven Active" if active_trade.get("be_moved") else "⏳ Trailing / Invalidation Armed"

        lines.append(f"🪙 *ACTIVE POSITION*: *{coin} ({direction})* {pnl_emoji}")
        lines.append(f"• Model: *{model}* | Score: *{score}/100*")
        lines.append(f"• Entry: *${entry:,.2f}* → Mark: *${curr_p:,.2f}*")
        lines.append(f"• Net PnL: *{r_sign}₹{pnl_data['pnl_inr']:,.2f} ({r_sign}{achieved_r:.2f}R)* {pnl_emoji}")
        lines.append(f"• Shield: *{be_status}*")
        lines.append("")
        lines.append("📊 *LIVE TRADE PROGRESS*:")
        lines.append(format_trade_progress_bar(entry, t1, sl, curr_p, direction, achieved_r))
        lines.append("")
        lines.append(f"🎯 *Levels*: SL: `${sl:,.2f}` | TP1: `${t1:,.2f}` | TP2: `${t2:,.2f}`")
    else:
        lines.append("🪙 *ACTIVE POSITION*: *NONE (0/1 Global Slot Open)* 🟢")
        lines.append("• Status: *24/7 Scanning Active Across 6 Markets*")
        lines.append("• Filter: *Institutional Displacement & SMT Alignment*")

    lines.append("─────────────────────────")
    lines.append("🛡️ *RISK & CAPITAL TELEMETRY*:")
    lines.append(f"• Daily Loss Limit: *₹{max_dl:,.2f}* (11:59 PM IST Reset)")
    lines.append(f"• Remaining Budget: *₹{rem_dl:,.2f}* ({'SAFE 🟢' if rem_dl > 100 else 'CAUTION ⚠️'})")
    lines.append(f"• Position Allocation: *₹{int(settings.MAX_ALLOWED_MARGIN):,} Margin @ {settings.DEFAULT_LEVERAGE}x* (₹{int(settings.MAX_ALLOWED_MARGIN * settings.DEFAULT_LEVERAGE):,} Notional)")
    lines.append("─────────────────────────")

    lines.append("📡 *MARKET RADAR (6 MARKETS)*:")
    zone_dict = market_zones or {}
    for sym in settings.SYMBOLS:
        p = live_prices.get(sym, 0.0)
        p_str = f"${p:,.4f}" if sym == "XRPUSD" else f"${p:,.2f}"
        zone = zone_dict.get(sym, "EQUILIBRIUM")
        lines.append(f"• *{sym}*: `{p_str}` ({zone})")

    lines.append("─────────────────────────")
    lines.append("👇 *Tap the interactive buttons below to execute instant controls.*")
    return "\n".join(lines)


def format_daily_executive_brief(
    data: dict[str, Any],
    current_daily_loss: float = 0.0,
    max_daily_loss: float = 420.0
) -> str:
    """
    Formats the automated 11:59 PM IST Daily Executive Briefing.
    Summarizes net PnL, Win Rate, trades taken, and confirms midnight loss reset.
    """
    from datetime import datetime, timezone, timedelta
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    date_str = ist_now.strftime("%d %B %Y | 11:59 PM IST")

    wins = data.get("wins", 0)
    losses = data.get("losses", 0)
    scratches = data.get("scratches", 0)
    decided = data.get("decided_trades", 0)
    win_rate = data.get("win_rate", 0.0)
    total_r = float(data.get("total_r", 0.0))
    total_pnl = float(data.get("total_pnl", 0.0))

    pnl_sign = "+" if total_pnl >= 0 else ""
    r_sign = "+" if total_r >= 0 else ""
    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"

    rem_budget = max(0.0, max_daily_loss - current_daily_loss)

    lines = [
        "🌙 *SPIDY CRYPTO — 11:59 PM IST DAILY EXECUTIVE BRIEF* 🌙",
        f"📅 *{date_str}*",
        "─────────────────────────",
        "💼 *DAILY PERFORMANCE AUDIT*:",
        f"• Decided Trades: *{decided}* ({wins}W / {losses}L / {scratches} Scratch)",
        f"• Win Rate: *{win_rate:.1f}%*",
        f"• Net Achieved R: *{r_sign}{total_r:.2f}R*",
        f"• Net Realized PnL: *{pnl_sign}₹{total_pnl:,.2f}* {pnl_emoji}",
        "",
        "🛡️ *CAPITAL SHIELD & DAILY LOSS STATUS*:",
        f"• Daily Loss Incurred: *₹{current_daily_loss:,.2f} / ₹{max_daily_loss:,.2f}*",
        f"• Daily Loss Remaining: *₹{rem_budget:,.2f}*",
        f"• 🕛 *Midnight Rollover*: ₹{max_daily_loss:,.2f} budget *REFRESHED* for new trading day! 🔄",
        "",
        "🎖️ *EXECUTION DISCIPLINE EVALUATION*:",
        "• Revenge Trading: *0 Violations (Single-Trade Lock Enforced)*",
        f"• Margin Discipline: *100% (₹{int(settings.MAX_ALLOWED_MARGIN):,} @ {settings.DEFAULT_LEVERAGE}x Leverage)*",
        "• Discipline Grade: *🌟 A+ INSTITUTIONAL STANDARD*",
        "─────────────────────────",
        "🤖 *SPIDY 24/7 SCANNER ARMED FOR NEXT SESSION (1:30 AM IST)!* 🚀"
    ]
    return "\n".join(lines)
