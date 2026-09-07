from datetime import datetime, timezone, timedelta

IST_TZ = timezone(timedelta(hours=5, minutes=30))

def get_ist_now() -> datetime:
    """Returns the current datetime in Indian Standard Time (UTC+5:30)."""
    return datetime.now(IST_TZ)
