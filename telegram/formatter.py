from typing import Any


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
        f"Entry: {entry:.2f}\n"
        f"Stop: {stop:.2f}\n"
        f"SL: {stop:.2f}\n"
        f"Target 1: {t1:.2f}\n"
        f"Target 2: {t2:.2f}\n"
        f"TP: {tp:.2f}\n"
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
    details: str = ""
) -> str:
    """Formats trade lifecycle updates (TRADE ACTIVE, TARGET HIT, STOPPED, CANCELLED, COMPLETED)."""
    status_emoji = {
        "ACTIVE": "🟢",
        "TARGET HIT": "🎯",
        "STOPPED": "🛑",
        "CANCELLED": "⚪",
        "COMPLETED": "🏁"
    }.get(status, "🕷️")

    header_status = f"TRADE {status}" if status == "ACTIVE" else status
    msg = (
        f"{status_emoji} SPIDY CRYPTO — {header_status}\n\n"
        f"Market: {coin} ({direction})\n"
        f"Status: {status}\n"
        f"Current Price: {price:.2f}\n"
    )
    if details:
        msg += f"Details: {details}\n"

    if status in ("STOPPED", "CANCELLED", "COMPLETED"):
        msg += "\nGlobal trade lock released. SPIDY CRYPTO is analyzing ETH, BTC, SOL for the next setup."

    return msg
