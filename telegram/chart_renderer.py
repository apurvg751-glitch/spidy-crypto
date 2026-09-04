import io
import time
from typing import Optional, Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from market_data.models import Candle


class TradeChartRenderer:
    """
    High-Definition In-Memory Institutional Chart Renderer.
    Renders dark-mode neon candlestick charts with exact Entry, Stop Loss,
    and Target annotations for Telegram mobile alerts.
    """

    @staticmethod
    def render_trade_chart(
        coin: str,
        direction: str,
        entry: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
        candles: list[Candle],
        model_name: str = "Institutional 100/100 Sniper ⭐",
        score: int = 100,
        rr: float = 2.5
    ) -> bytes:
        """Renders an HD chart and returns PNG image bytes."""
        plot_candles = candles[-40:] if len(candles) >= 40 else candles
        if not plot_candles:
            return b""

        fig, ax = plt.subplots(figsize=(10, 5.5), dpi=140)
        fig.patch.set_facecolor("#0b0e14")
        ax.set_facecolor("#10141e")

        n = len(plot_candles)

        # 1. Draw Candlesticks
        for i, c in enumerate(plot_candles):
            is_bull = c.close >= c.open
            color = "#00e676" if is_bull else "#ff1744"
            edge_color = "#00f0ff" if is_bull else "#ff5252"

            # Wicks
            ax.plot([i, i], [c.low, c.high], color=color, linewidth=1.2, alpha=0.9)

            # Candle Body
            body_bottom = min(c.open, c.close)
            body_height = max(abs(c.close - c.open), (c.high - c.low) * 0.05 if (c.high - c.low) > 0 else 0.01)
            rect = patches.Rectangle(
                (i - 0.35, body_bottom),
                0.7,
                body_height,
                facecolor=color,
                edgecolor=edge_color,
                linewidth=0.8,
                alpha=0.95
            )
            ax.add_patch(rect)

        # 2. Price Formatting
        def fmt(p: float) -> str:
            if coin == "XRPUSD":
                return f"${p:,.4f}"
            elif coin == "AVAXUSD":
                return f"${p:,.3f}"
            elif coin == "BTCUSD":
                return f"${p:,.1f}"
            return f"${p:,.2f}"

        # 3. Horizontal Price Levels
        ax.axhline(entry, color="#00f0ff", linestyle="--", linewidth=1.8, alpha=0.95, label="Entry")
        ax.axhline(stop_loss, color="#ff1744", linestyle="-", linewidth=2.0, alpha=0.95, label="Stop Loss")
        ax.axhline(target_1, color="#00e676", linestyle="--", linewidth=1.8, alpha=0.95, label="Target 1")
        ax.axhline(target_2, color="#76ff03", linestyle="--", linewidth=1.8, alpha=0.95, label="Target 2")

        # 4. Level Badges on Right Margin
        right_x = n - 0.2
        ax.text(
            right_x, entry, f"  ENTRY: {fmt(entry)}",
            color="#00f0ff", fontsize=9, fontweight="bold",
            va="center", ha="left",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#0b1726", edgecolor="#00f0ff", alpha=0.9)
        )
        ax.text(
            right_x, stop_loss, f"  SL: {fmt(stop_loss)} (-1.0R / ₹150)",
            color="#ff1744", fontsize=9, fontweight="bold",
            va="center", ha="left",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#260b0f", edgecolor="#ff1744", alpha=0.9)
        )
        ax.text(
            right_x, target_1, f"  TP1: {fmt(target_1)} (+1.6R / +₹240)",
            color="#00e676", fontsize=9, fontweight="bold",
            va="center", ha="left",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#0b2612", edgecolor="#00e676", alpha=0.9)
        )
        ax.text(
            right_x, target_2, f"  TP2: {fmt(target_2)} (+{rr:.1f}R / +₹{int(150*rr)})",
            color="#76ff03", fontsize=9, fontweight="bold",
            va="center", ha="left",
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#1a260b", edgecolor="#76ff03", alpha=0.9)
        )

        # 5. Styling & Header
        title_text = f"SPIDY MASTER V3.0  |  {coin} {direction.upper()}  |  Score: {score}/100  |  RR: 1:{rr:.1f}"
        ax.set_title(title_text, color="#ffffff", fontsize=11, fontweight="bold", pad=12, loc="left")
        fig.text(0.125, 0.90, f"Model: {model_name}  •  Delta Exchange India Live Data", color="#90a4ae", fontsize=8.5)

        ax.grid(True, color="#1e293b", linestyle=":", linewidth=0.7, alpha=0.7)
        ax.tick_params(colors="#64748b", labelsize=8)
        for spine in ax.spines.values():
            spine.set_color("#1e293b")

        all_prices = [c.low for c in plot_candles] + [c.high for c in plot_candles] + [entry, stop_loss, target_1, target_2]
        min_p = min(all_prices)
        max_p = max(all_prices)
        p_padding = (max_p - min_p) * 0.08
        ax.set_ylim(min_p - p_padding, max_p + p_padding)
        ax.set_xlim(-1, n + 8)
        ax.set_xticks([])

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
