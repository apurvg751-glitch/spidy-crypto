import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from market_data.models import Candle
from storage.database import Database
from trade_manager.manager import TradeManager
from telegram.notifier import TelegramNotifier


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_spidy.db"
    return Database(db_path=db_file)


@pytest.fixture
def mock_trade_manager(temp_db):
    notifier = TelegramNotifier(db=temp_db, bot_token="MOCK_TOKEN", chat_id="12345")
    tm = TradeManager(db=temp_db, telegram=notifier, cooldown_seconds=0)
    return tm


def generate_candles(
    base_price: float,
    count: int = 50,
    interval_seconds: int = 300,
    trend: str = "FLAT",
    volatility: float = 0.005,
    volume_base: float = 1000.0,
    start_time: int = 1700000000
) -> list[Candle]:
    """Generates synthetic deterministic candles for unit testing."""
    candles = []
    p = base_price

    for i in range(count):
        t = start_time + (i * interval_seconds)
        if trend == "UP":
            delta = p * volatility * 0.4
        elif trend == "DOWN":
            delta = -p * volatility * 0.4
        else:
            delta = (1 if i % 2 == 0 else -1) * (p * volatility * 0.2)

        open_p = p
        close_p = p + delta
        high_p = max(open_p, close_p) + (p * volatility * 0.3)
        low_p = min(open_p, close_p) - (p * volatility * 0.3)
        vol = volume_base * (1.5 if i == count - 1 else 1.0)

        candles.append(Candle(
            time=t,
            open=round(open_p, 2),
            high=round(high_p, 2),
            low=round(low_p, 2),
            close=round(close_p, 2),
            volume=round(vol, 2),
            is_closed=True
        ))
        p = close_p

    return candles


def make_candle(
    time_val: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 1000.0,
    is_closed: bool = True
) -> Candle:
    """Helper to create a discrete deterministic candle."""
    return Candle(
        time=int(time_val),
        open=float(open_p),
        high=float(high_p),
        low=float(low_p),
        close=float(close_p),
        volume=float(volume),
        is_closed=is_closed
    )


@pytest.fixture(autouse=True)
def disable_real_telegram_in_tests(monkeypatch):
    """Guarantees automated test runs NEVER dispatch messages to the user's live Telegram bot."""
    async def mock_send(*args, **kwargs):
        return True
    monkeypatch.setattr(TelegramNotifier, "send_message", mock_send)
    monkeypatch.setattr(TelegramNotifier, "send_trade_detected_alert", mock_send)
    monkeypatch.setattr(TelegramNotifier, "send_trade_lifecycle_update", mock_send)

