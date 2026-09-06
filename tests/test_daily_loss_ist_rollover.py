import pytest
from datetime import datetime, timezone, timedelta
from storage.database import Database
from trade_manager.manager import TradeManager
from config.settings import settings


def test_daily_loss_ist_rollover_resets_loss(tmp_path):
    """Verifies that when a new IST trading day starts (11:59 PM IST rollover), daily loss resets to 0."""
    db = Database(db_path=str(tmp_path / "test_rollover.db"))
    tm = TradeManager(db=db)

    # Simulate accumulated loss today
    tm.current_daily_loss = 350.0
    tm.check_daily_loss_reset()
    assert tm.current_daily_loss == 350.0  # Same date, not reset

    # Simulate that current_daily_date was yesterday (prior IST day)
    tm.current_daily_date = "2026-09-05"
    rolled = tm.check_daily_loss_reset()

    assert rolled is True
    assert tm.current_daily_loss == 0.0
    assert db.get_config("daily_loss_amount") == "0.0"


def test_daily_loss_persists_across_restart_on_same_ist_day(tmp_path):
    """Verifies that if the app restarts on the same IST day, accumulated loss is restored from DB."""
    db_file = str(tmp_path / "test_persist.db")
    db = Database(db_path=db_file)
    tm1 = TradeManager(db=db)

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(ist_tz).strftime("%Y-%m-%d")

    # Simulate recording a loss today
    tm1.current_daily_date = today_ist
    tm1.current_daily_loss = 250.0
    db.set_config("daily_loss_date", today_ist)
    db.set_config("daily_loss_amount", "250.0")

    # Now simulate server restart
    tm2 = TradeManager(db=Database(db_path=db_file))
    assert tm2.current_daily_loss == 250.0
    assert tm2.current_daily_date == today_ist


def test_daily_loss_resets_on_restart_if_past_ist_midnight(tmp_path):
    """Verifies that if the app restarts after midnight IST (new date), daily loss initializes fresh at 0.0."""
    db_file = str(tmp_path / "test_restart_midnight.db")
    db = Database(db_path=db_file)

    # Simulate yesterday's date in DB with max loss hit
    db.set_config("daily_loss_date", "2026-09-01")
    db.set_config("daily_loss_amount", "420.0")

    # Start new TradeManager today
    tm = TradeManager(db=db)
    assert tm.current_daily_loss == 0.0
    assert db.get_config("daily_loss_amount") == "0.0"
