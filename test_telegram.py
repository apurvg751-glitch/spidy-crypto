import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config.settings import settings
from telegram.notifier import TelegramNotifier


async def main():
    print("=" * 60)
    print("🕷️ SPIDY CRYPTO — TELEGRAM CONNECTION TEST")
    print("=" * 60)

    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()

    if not token or not chat_id:
        print("[ERROR] Telegram credentials are not set!")
        print("Please edit the .env file in the project folder:")
        print("  C:\\Users\\admin\\.gemini\\antigravity\\scratch\\spidy_crypto\\.env")
        print("and fill in:")
        print("  TELEGRAM_BOT_TOKEN=your_token_here")
        print("  TELEGRAM_CHAT_ID=your_chat_id_here")
        return

    print(f"Bot Token: {token[:6]}...{token[-4:]}")
    print(f"Chat ID:   {chat_id}")
    print("\nSending test ping to Telegram...")

    notifier = TelegramNotifier()
    success = await notifier.send_message(
        "🕷️ <b>SPIDY CRYPTO — Connection Verified!</b>\n\n"
        "Your Telegram alerts are now connected and operational.\n"
        "You will receive alerts here whenever a setup is selected!"
    )
    await notifier.close()

    if success:
        print("\n[SUCCESS] Test message delivered to Telegram!")
    else:
        print("\n[FAILED] Could not deliver message. Please verify your Bot Token and Chat ID.")


if __name__ == "__main__":
    asyncio.run(main())
