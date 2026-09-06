import io
import logging
from typing import List, Optional, Union, Any
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend safe for cloud servers
import matplotlib.pyplot as plt
import matplotlib.patches as patches

logger = logging.getLogger("spidy.chart_generator")


def _extract_candle_vals(c: Any) -> tuple[float, float, float, float]:
    """Helper to safely extract open, high, low, close from dict or Candle object."""
    if hasattr(c, "open") and hasattr(c, "high") and hasattr(c, "low") and hasattr(c, "close"):
        return float(c.open), float(c.high), float(c.low), float(c.close)
    elif isinstance(c, dict):
        o = float(c.get("open", c.get("o", 0.0)))
        h = float(c.get("high", c.get("h", 0.0)))
        l = float(c.get("low", c.get("l", 0.0)))
        cl = float(c.get("close", c.get("c", 0.0)))
        return o, h, l, cl
    return 0.0, 0.0, 0.0, 0.0


def generate_trade_chart(
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    target_1: float,
    target_2: float,
    candles: Optional[List[Any]] = None,
    htf_walls: Optional[List[float]] = None
) -> bytes:
    """
    Renders an institutional dark-mode candlestick chart with Entry, SL, TP1, TP2,
    and ⚪ HTF White Line (Institutional Origin) overlays.
    Returns PNG image bytes in memory (ready for Telegram send_photo).
    """
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=130)
    fig.patch.set_facecolor("#0a0e17")
    ax.set_facecolor("#0d1322")

    # If candles are provided, plot real or simulated candlesticks
    if candles and len(candles) >= 5:
        sub_candles = candles[-35:] if len(candles) >= 35 else candles
        n_bars = len(sub_candles)
        prices_open, prices_high, prices_low, prices_close = [], [], [], []
        for c in sub_candles:
            o, h, l, cl = _extract_candle_vals(c)
            prices_open.append(o if o > 0 else entry)
            prices_high.append(h if h > 0 else entry)
            prices_low.append(l if l > 0 else entry)
            prices_close.append(cl if cl > 0 else entry)
    else:
        # Generate baseline representation around entry
        n_bars = 20
        span = abs(entry - stop_loss) if abs(entry - stop_loss) > 0 else (entry * 0.01)
        prices_open = [entry - (span * 0.4) + (i * span * 0.03) for i in range(n_bars)]
        prices_close = [p + (span * 0.05) if i % 2 == 0 else p - (span * 0.03) for i, p in enumerate(prices_open)]
        prices_high = [max(o, c) + (span * 0.08) for o, c in zip(prices_open, prices_close)]
        prices_low = [min(o, c) - (span * 0.08) for o, c in zip(prices_open, prices_close)]

    # Plot candlesticks
    for i in range(n_bars):
        o, c = prices_open[i], prices_close[i]
        h, l = prices_high[i], prices_low[i]
        color = "#00f0a8" if c >= o else "#ff3b69"  # Neon green / vibrant crimson
        # Wicks
        ax.plot([i, i], [l, h], color=color, linewidth=1.2, alpha=0.85)
        # Body
        body_bottom = min(o, c)
        body_height = max(abs(c - o), (h - l) * 0.04 if (h - l) > 0 else (entry * 0.001))
        rect = patches.Rectangle((i - 0.35, body_bottom), 0.7, body_height, facecolor=color, edgecolor=color, alpha=0.9)
        ax.add_patch(rect)

    # Format price helper
    def fmt(p: float) -> str:
        if symbol == "XRPUSD":
            return f"${p:,.4f}"
        elif symbol == "AVAXUSD":
            return f"${p:,.3f}"
        elif symbol == "BTCUSD":
            return f"${p:,.1f}"
        return f"${p:,.2f}"

    x_min, x_max = -0.5, n_bars - 0.5

    # Plot Entry, Stop Loss, TP1, TP2 Overlay Lines
    ax.hlines(entry, x_min, x_max, colors="#00c8ff", linestyles="--", linewidth=1.8, label=f"Entry: {fmt(entry)}")
    ax.hlines(stop_loss, x_min, x_max, colors="#ff3366", linestyles="-", linewidth=1.8, label=f"Stop Loss: {fmt(stop_loss)}")
    ax.hlines(target_1, x_min, x_max, colors="#00ffaa", linestyles=":", linewidth=1.8, label=f"Target 1: {fmt(target_1)}")
    ax.hlines(target_2, x_min, x_max, colors="#00e5ff", linestyles=":", linewidth=1.8, label=f"Target 2: {fmt(target_2)}")

    # ⚪ HTF Institutional Origin White Line Overlays
    if htf_walls:
        for idx, wall in enumerate(htf_walls):
            if wall > 0:
                ax.hlines(
                    wall, x_min, x_max,
                    colors="#ffffff",
                    linestyles="--",
                    linewidth=2.0,
                    alpha=0.95,
                    label=f"⚪ HTF Wall: {fmt(wall)}" if idx == 0 else None
                )
                ax.text(
                    x_max, wall, f" ⚪ HTF ORIGIN: {fmt(wall)}",
                    color="#ffffff", fontweight="bold", fontsize=8,
                    va="center", ha="left",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#1e293b", edgecolor="#ffffff", alpha=0.9)
                )

    # Price badges on right side
    ax.text(x_max, entry, f" ENTRY: {fmt(entry)}", color="#00c8ff", fontsize=8, fontweight="bold", va="center")
    ax.text(x_max, stop_loss, f" SL: {fmt(stop_loss)}", color="#ff3366", fontsize=8, fontweight="bold", va="center")
    ax.text(x_max, target_1, f" TP1: {fmt(target_1)}", color="#00ffaa", fontsize=8, fontweight="bold", va="center")
    ax.text(x_max, target_2, f" TP2: {fmt(target_2)}", color="#00e5ff", fontsize=8, fontweight="bold", va="center")

    # Styling & Grid
    ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
    ax.tick_params(colors="#8a99ad", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    all_levels = [entry, stop_loss, target_1, target_2] + prices_high + prices_low
    if htf_walls:
        all_levels.extend([w for w in htf_walls if w > 0])
    min_lvl = min(all_levels)
    max_lvl = max(all_levels)
    pad = (max_lvl - min_lvl) * 0.08 if max_lvl > min_lvl else entry * 0.01
    ax.set_ylim(min_lvl - pad, max_lvl + pad)
    ax.set_xlim(x_min - 0.5, x_max + 7.5)

    dir_color = "#00f0a8" if direction.upper() == "LONG" else "#ff3b69"
    ax.set_title(
        f"SPIDY CRYPTO 2.0  •  {symbol} {direction.upper()} EXECUTION  •  ⚪ HTF ORIGIN ACTIVE",
        color="#ffffff", fontsize=11, fontweight="bold", pad=12
    )
    ax.legend(loc="upper left", facecolor="#0a0e17", edgecolor="#1e293b", labelcolor="#cbd5e1", fontsize=8.5)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_symbol_analysis_chart(
    symbol: str,
    current_price: float,
    candles: Optional[List[Any]] = None,
    htf_walls: Optional[List[float]] = None,
    active_trade: Optional[dict] = None
) -> bytes:
    """
    Renders on-demand chart snapshot for `/chart [coin]`.
    If active_trade exists for this coin, renders the full trade overlay.
    Otherwise renders institutional market structure with current price and ⚪ HTF White Line.
    """
    if active_trade and active_trade.get("coin") == symbol:
        return generate_trade_chart(
            symbol=symbol,
            direction=active_trade.get("direction", "LONG"),
            entry=float(active_trade.get("entry", current_price)),
            stop_loss=float(active_trade.get("stop_loss", current_price * 0.99)),
            target_1=float(active_trade.get("target_1", current_price * 1.015)),
            target_2=float(active_trade.get("target_2", current_price * 1.025)),
            candles=candles,
            htf_walls=htf_walls
        )

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=130)
    fig.patch.set_facecolor("#0a0e17")
    ax.set_facecolor("#0d1322")

    if candles and len(candles) >= 5:
        sub_candles = candles[-35:] if len(candles) >= 35 else candles
        n_bars = len(sub_candles)
        prices_open, prices_high, prices_low, prices_close = [], [], [], []
        for c in sub_candles:
            o, h, l, cl = _extract_candle_vals(c)
            prices_open.append(o if o > 0 else current_price)
            prices_high.append(h if h > 0 else current_price)
            prices_low.append(l if l > 0 else current_price)
            prices_close.append(cl if cl > 0 else current_price)
    else:
        n_bars = 20
        span = current_price * 0.015
        prices_open = [current_price - (span * 0.5) + (i * span * 0.05) for i in range(n_bars)]
        prices_close = [p + (span * 0.06) if i % 2 == 0 else p - (span * 0.04) for i, p in enumerate(prices_open)]
        prices_high = [max(o, c) + (span * 0.08) for o, c in zip(prices_open, prices_close)]
        prices_low = [min(o, c) - (span * 0.08) for o, c in zip(prices_open, prices_close)]

    for i in range(n_bars):
        o, c = prices_open[i], prices_close[i]
        h, l = prices_high[i], prices_low[i]
        color = "#00f0a8" if c >= o else "#ff3b69"
        ax.plot([i, i], [l, h], color=color, linewidth=1.2, alpha=0.85)
        body_bottom = min(o, c)
        body_height = max(abs(c - o), (h - l) * 0.04 if (h - l) > 0 else (current_price * 0.001))
        rect = patches.Rectangle((i - 0.35, body_bottom), 0.7, body_height, facecolor=color, edgecolor=color, alpha=0.9)
        ax.add_patch(rect)

    def fmt(p: float) -> str:
        if symbol == "XRPUSD":
            return f"${p:,.4f}"
        elif symbol == "AVAXUSD":
            return f"${p:,.3f}"
        elif symbol == "BTCUSD":
            return f"${p:,.1f}"
        return f"${p:,.2f}"

    x_min, x_max = -0.5, n_bars - 0.5
    ax.hlines(current_price, x_min, x_max, colors="#00f0ff", linestyles="--", linewidth=1.8, label=f"Live Mark: {fmt(current_price)}")
    ax.text(x_max, current_price, f" LIVE: {fmt(current_price)}", color="#00f0ff", fontsize=8, fontweight="bold", va="center")

    # ⚪ HTF White Line
    if htf_walls:
        for idx, wall in enumerate(htf_walls):
            if wall > 0:
                ax.hlines(
                    wall, x_min, x_max,
                    colors="#ffffff",
                    linestyles="--",
                    linewidth=2.0,
                    alpha=0.95,
                    label=f"⚪ HTF Wall: {fmt(wall)}" if idx == 0 else None
                )
                ax.text(
                    x_max, wall, f" ⚪ HTF ORIGIN: {fmt(wall)}",
                    color="#ffffff", fontweight="bold", fontsize=8,
                    va="center", ha="left",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="#1e293b", edgecolor="#ffffff", alpha=0.9)
                )

    ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
    ax.tick_params(colors="#8a99ad", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    all_levels = [current_price] + prices_high + prices_low
    if htf_walls:
        all_levels.extend([w for w in htf_walls if w > 0])
    min_lvl = min(all_levels)
    max_lvl = max(all_levels)
    pad = (max_lvl - min_lvl) * 0.08 if max_lvl > min_lvl else current_price * 0.01
    ax.set_ylim(min_lvl - pad, max_lvl + pad)
    ax.set_xlim(x_min - 0.5, x_max + 7.5)

    ax.set_title(
        f"SPIDY CRYPTO 2.0  •  {symbol} INSTITUTIONAL MARKET STRUCTURE  •  ⚪ HTF ORIGIN",
        color="#ffffff", fontsize=11, fontweight="bold", pad=12
    )
    ax.legend(loc="upper left", facecolor="#0a0e17", edgecolor="#1e293b", labelcolor="#cbd5e1", fontsize=8.5)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
