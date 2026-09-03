from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from structure.kill_zones import KillZoneEngine, KillZoneStatus
from indicators.smt_divergence import SMTResult


class SessionBriefingGenerator:
    """
    Automated Institutional Session Macro Briefing Generator for Telegram.
    Formats executive pre-session gameplans for Apurv.
    """

    IST_OFFSET = timedelta(hours=5, minutes=30)

    @classmethod
    def format_morning_briefing(
        cls,
        prices: Dict[str, float],
        kill_zone: KillZoneStatus,
        smt: Optional[SMTResult] = None,
        market_analysis: Optional[Dict[str, Any]] = None
    ) -> str:
        now_ist = datetime.now(timezone.utc) + cls.IST_OFFSET
        date_str = now_ist.strftime("%d %B %Y | %I:%M %p IST")

        btc_p = prices.get("BTCUSD", 0.0)
        eth_p = prices.get("ETHUSD", 0.0)
        sol_p = prices.get("SOLUSD", 0.0)

        ash_str = f"${kill_zone.asian_high:,.2f}" if kill_zone.asian_high else "Calculating..."
        asl_str = f"${kill_zone.asian_low:,.2f}" if kill_zone.asian_low else "Calculating..."
        smt_desc = smt.description if smt else "Correlated Lockstep"

        lines = [
            "🌅 *SPIDY CRYPTO — MORNING MACRO BRIEFING*",
            f"📅 *{date_str}*",
            "─────────────────────────",
            "📊 *CURRENT MARKET OVERVIEW*:",
            f"• *BTCUSD*: `${btc_p:,.2f}`",
            f"• *ETHUSD*: `${eth_p:,.2f}`",
            f"• *SOLUSD*: `${sol_p:,.2f}`",
            "",
            "🎯 *ASIAN LIQUIDITY POOLS (KEY TARGETS)*:",
            f"• Asian High (ASH / Buy-Side): *{ash_str}*",
            f"• Asian Low (ASL / Sell-Side): *{asl_str}*",
            "💡 _Gameplan: Watch for London Judas Sweep of ASH or ASL between 1:30 PM – 4:30 PM IST._",
            "",
            "📉 *SMT CORRELATION TOOL*:",
            f"• Status: *{smt_desc}*",
            "",
            "🏛️ *TODAY'S EXECUTION DIRECTIVE*:",
            "• Primary Watch: *BTCUSD* (Lead Macro Asset)",
            "• Risk Protocol: *Single-Trade Lock Active (1/1)*",
            "• Invalidation Filter: *Top 25% & Bottom 25% Barrier Active*",
            "─────────────────────────",
            "🤖 *SPIDY IS LIVE & SCANNING FOR A+ CONFLUENCE!*"
        ]
        return "\n".join(lines)

    @classmethod
    def format_ny_briefing(
        cls,
        prices: Dict[str, float],
        kill_zone: KillZoneStatus,
        smt: Optional[SMTResult] = None
    ) -> str:
        now_ist = datetime.now(timezone.utc) + cls.IST_OFFSET
        date_str = now_ist.strftime("%d %B %Y | %I:%M %p IST")

        btc_p = prices.get("BTCUSD", 0.0)
        eth_p = prices.get("ETHUSD", 0.0)
        sol_p = prices.get("SOLUSD", 0.0)

        lines = [
            "🌆 *SPIDY CRYPTO — NEW YORK OPEN BRIEFING*",
            f"📅 *{date_str}*",
            "─────────────────────────",
            "🚀 *NEW YORK AM KILL ZONE (7:00 PM – 10:30 PM IST)*",
            f"• *BTCUSD*: `${btc_p:,.2f}`",
            f"• *ETHUSD*: `${eth_p:,.2f}`",
            f"• *SOLUSD*: `${sol_p:,.2f}`",
            "",
            "🔥 *INSTITUTIONAL EXPECTATION*:",
            "• High-volume US market open liquidity expansion.",
            "• SMT Divergence confirmation will trigger instant Model 10 Sniper setups.",
            "• 3-Stage Partial Scaling (50% TP1 / 30% TP2 / 20% Runner) armed.",
            "─────────────────────────",
            "🎯 *READY FOR PRIME TIME EXECUTION!*"
        ]
        return "\n".join(lines)
