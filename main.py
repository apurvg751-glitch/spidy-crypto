import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn
from config.settings import settings


def run():
    print(f"""
    ================================================================
    SPIDY CRYPTO - AUTONOMOUS TRADING ASSISTANT (CORE V1)
    ================================================================
    Markets Monitored: {', '.join(settings.SYMBOLS)}
    Exchange Data: Delta Exchange India (api.india.delta.exchange)
    Global Lock: MAX_ACTIVE_TRADES = {settings.MAX_ACTIVE_TRADES}
    Dashboard URL: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}
    Telegram Alerts: {'CONFIGURED' if settings.TELEGRAM_BOT_TOKEN else 'OFFLINE (Set TELEGRAM_BOT_TOKEN)'}
    ================================================================
    """)
    uvicorn.run(
        "server:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run()
