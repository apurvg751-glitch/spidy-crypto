import io
import logging
from datetime import datetime
from typing import Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger("spidy.social_cards")


def generate_pnl_social_card(
    coin: str,
    direction: str,
    pnl_inr: float,
    achieved_r: float,
    win_rate: float = 100.0,
    execution_grade: str = "A+",
    exit_reason: str = "Profit Secured 🔒"
) -> bytes:
    """
    Renders an institutional 16:9 social media announcement card
    highlighting trade win, realized PnL in INR, R-multiple, and SPIDY branding.
    """
    # Sanitize text for matplotlib fonts
    clean_exit = exit_reason.encode("ascii", "ignore").decode().strip() or exit_reason

    fig, ax = plt.subplots(figsize=(10, 5.625), dpi=120)  # 1200x675 16:9
    fig.patch.set_facecolor("#080c14")
    ax.set_facecolor("#0d1322")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color("#1e293b")

    # Header branding
    ax.text(0.08, 0.88, "SPIDY CRYPTO", color="#00e5ff", fontsize=22, fontweight="heavy", transform=ax.transAxes)
    ax.text(0.38, 0.89, "•  INSTITUTIONAL QUANT TRADING", color="#64748b", fontsize=11, fontweight="bold", transform=ax.transAxes)

    # Trade Pair & Direction Pill
    dir_color = "#00f0a8" if direction.upper() == "LONG" else "#ff3b69"
    ax.text(0.08, 0.74, f"{coin}  |  {direction.upper()}", color=dir_color, fontsize=18, fontweight="bold", transform=ax.transAxes)

    # Big Profit Display
    pnl_sign = "+" if pnl_inr >= 0 else "-"
    pnl_color = "#00f0a8" if pnl_inr >= 0 else "#ff3b69"
    ax.text(0.08, 0.50, f"{pnl_sign}₹{abs(pnl_inr):,.2f}", color=pnl_color, fontsize=38, fontweight="heavy", transform=ax.transAxes)

    r_sign = "+" if achieved_r >= 0 else ""
    ax.text(0.08, 0.38, f"Achieved: {r_sign}{achieved_r:.2f}R  •  {clean_exit}", color="#cbd5e1", fontsize=13, transform=ax.transAxes)

    # Metrics Box (Right side)
    rect = plt.Rectangle((0.62, 0.28), 0.30, 0.48, facecolor="#131c31", edgecolor="#263554", linewidth=1.2, transform=ax.transAxes)
    ax.add_patch(rect)

    ax.text(0.66, 0.66, "SYSTEM STATS", color="#64748b", fontsize=10, fontweight="bold", transform=ax.transAxes)
    ax.text(0.66, 0.55, f"Win Rate: {win_rate:.1f}%", color="#ffffff", fontsize=13, fontweight="bold", transform=ax.transAxes)
    ax.text(0.66, 0.44, f"Discipline: Grade {execution_grade}", color="#00e5ff", fontsize=13, fontweight="bold", transform=ax.transAxes)
    ax.text(0.66, 0.33, "Exchange: Delta India", color="#94a3b8", fontsize=10, transform=ax.transAxes)

    # Footer
    today = datetime.now().strftime("%B %d, %Y")
    ax.text(0.08, 0.12, f"Verified Autonomous Execution  •  {today}", color="#475569", fontsize=9, transform=ax.transAxes)
    ax.text(0.70, 0.12, "Powered by SPIDY 2.0", color="#475569", fontsize=9, fontweight="bold", transform=ax.transAxes)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
