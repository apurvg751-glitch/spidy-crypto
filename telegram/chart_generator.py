import io
import logging
from typing import List, Optional, Union
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend safe for cloud servers
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

logger = logging.getLogger("spidy.chart_generator")


def generate_trade_chart(
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    target_1: float,
    target_2: float,
    candles: Optional[List[dict]] = None
) -> bytes:
    """
    Renders an institutional dark-mode candlestick chart with Entry, SL, and TP overlays.
    Returns PNG image bytes in memory (ready for Telegram send_photo).
    """
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)
    fig.patch.set_facecolor("#0a0e17")
    ax.set_facecolor("#0d1322")

    # If candles are provided, plot real or simulated candlesticks
    if candles and len(candles) >= 5:
        prices_high = [float(c.get("high", c.get("h", entry))) for c in candles]
        prices_low = [float(c.get("low", c.get("l", entry))) for c in candles]
        prices_open = [float(c.get("open", c.get("o", entry))) for c in candles]
        prices_close = [float(c.get("close", c.get("c", entry))) for c in candles]
        n_bars = len(candles)
    else:
        # Generate baseline representation around entry
        n_bars = 20
        span = abs(entry - stop_loss) if abs(entry - stop_loss) > 0 else (entry * 0.01)
        prices_open = [entry - (span * 0.4) + (i * span * 0.03) for i in range(n_bars)]
        prices_close = [p + (span * 0.05) if i % 2 == 0 else p - (span * 0.03) for i, p in enumerate(prices_open)]
        prices_high = [max(o, c) + (span * 0.08) for o, c in zip(prices_open, prices_close)]
        prices_low = [min(o, c) - (span * 0.08) for o, c in zip(prices_open, prices_close)]

    indices = list(range(n_bars))

    # Plot candlesticks
    for i in range(n_bars):
        o, c = prices_open[i], prices_close[i]
        h, l = prices_high[i], prices_low[i]
        color = "#00f0a8" if c >= o else "#ff3b69"  # Neon green / vibrant crimson
        # Wicks
        ax.plot([i, i], [l, h], color=color, linewidth=1.2, alpha=0.85)
        # Body
        body_bottom = min(o, c)
        body_height = max(abs(c - o), (h - l) * 0.04)
        rect = plt.Rectangle((i - 0.35, body_bottom), 0.7, body_height, facecolor=color, edgecolor=color, alpha=0.9)
        ax.add_patch(rect)

    # Plot Entry, Stop Loss, TP1, TP2 Overlay Lines
    x_min, x_max = -0.5, n_bars - 0.5
    ax.hlines(entry, x_min, x_max, colors="#00c8ff", linestyles="--", linewidth=1.8, label=f"Entry: ${entry:,.4f}")
    ax.hlines(stop_loss, x_min, x_max, colors="#ff3366", linestyles="-", linewidth=1.8, label=f"Stop Loss: ${stop_loss:,.4f}")
    ax.hlines(target_1, x_min, x_max, colors="#00ffaa", linestyles=":", linewidth=1.8, label=f"Target 1: ${target_1:,.4f}")
    ax.hlines(target_2, x_min, x_max, colors="#00e5ff", linestyles=":", linewidth=1.8, label=f"Target 2: ${target_2:,.4f}")

    # Styling & Grid
    ax.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
    ax.tick_params(colors="#8a99ad", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    dir_color = "#00f0a8" if direction.upper() == "LONG" else "#ff3b69"
    ax.set_title(f"SPIDY CRYPTO 2.0  •  {symbol} {direction.upper()} EXECUTION", color="#ffffff", fontsize=12, fontweight="bold", pad=12)
    ax.legend(loc="upper left", facecolor="#0a0e17", edgecolor="#1e293b", labelcolor="#cbd5e1", fontsize=9)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
