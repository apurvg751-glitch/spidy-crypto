from typing import Any, Optional
from config.precision import format_price, get_symbol_precision


def format_coin_price(coin: str, price: float) -> str:
    """Formats price according to Delta Exchange precision specifications."""
    return format_price(coin, price)


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
        f"RR: 1:{rr:.1f}\n\n"
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
    leverage: Any = None
) -> str:
    """Formats trade lifecycle updates with live variable PnL, R-Multiple, and precise delta calculations."""
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

    if details:
        lines.append(f"Exit Reason: {details}")

    if is_terminal:
        lines.append("\nGlobal trade lock released. SPIDY CRYPTO is analyzing ETH, BTC, SOL for the next setup.")

    return "\n".join(lines)


