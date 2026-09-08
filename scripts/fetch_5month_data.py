import os
import sys
import json
import time
import ssl
import urllib.request
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from market_data.models import Candle

CACHE_DIR = Path(__file__).parent.parent / "scratch" / "historical_candles"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = {
    "BTCUSD": "BTCUSDT",
    "ETHUSD": "ETHUSDT",
    "SOLUSD": "SOLUSDT",
    "XRPUSD": "XRPUSDT",
    "AVAXUSD": "AVAXUSDT"
}

def fetch_candles_range(binance_symbol: str, interval: str = "15m", days: int = 150) -> list[dict]:
    """Fetches continuous historical candlestick data from Binance public API."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    end_ts = int(time.time() * 1000)
    start_ts = end_ts - (days * 24 * 3600 * 1000)
    
    all_candles = []
    curr_start = start_ts
    
    print(f"Fetching {binance_symbol} ({interval}) over past {days} days...")
    
    while curr_start < end_ts:
        url = f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit=1000&startTime={curr_start}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=12) as resp:
                data = json.loads(resp.read().decode())
                if not data:
                    break
                for row in data:
                    all_candles.append({
                        "time": int(row[0] // 1000), # Unix timestamp in seconds
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                        "is_closed": True
                    })
                
                last_open_time = data[-1][0]
                if last_open_time <= curr_start:
                    break
                curr_start = last_open_time + 1
                time.sleep(0.05) # Polite sleep
        except Exception as e:
            print(f"  Warning fetching {binance_symbol}: {e}. Retrying in 1s...")
            time.sleep(1.0)
            
    # Deduplicate by timestamp
    deduped = []
    seen = set()
    for c in all_candles:
        if c["time"] not in seen:
            seen.add(c["time"])
            deduped.append(c)
            
    print(f"  -> Total bars fetched for {binance_symbol} ({interval}): {len(deduped)}")
    return deduped

def ensure_historical_data(days: int = 150):
    for local_sym, binance_sym in SYMBOLS.items():
        cache_file_15m = CACHE_DIR / f"{local_sym}_15m_{days}d.json"
        if not cache_file_15m.exists() or os.path.getsize(cache_file_15m) < 10000:
            c15 = fetch_candles_range(binance_sym, interval="15m", days=days)
            with open(cache_file_15m, "w", encoding="utf-8") as f:
                json.dump(c15, f)
        else:
            print(f"Cached data exists for {local_sym} (15m): {cache_file_15m.name}")

        cache_file_1h = CACHE_DIR / f"{local_sym}_1h_{days}d.json"
        if not cache_file_1h.exists() or os.path.getsize(cache_file_1h) < 10000:
            c1h = fetch_candles_range(binance_sym, interval="1h", days=days)
            with open(cache_file_1h, "w", encoding="utf-8") as f:
                json.dump(c1h, f)
        else:
            print(f"Cached data exists for {local_sym} (1h): {cache_file_1h.name}")

if __name__ == "__main__":
    ensure_historical_data(days=150)
    print("5-Month historical data download and cache complete.")
