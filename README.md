# SPIDY CRYPTO — Autonomous Trading Assistant (Core Version 1)

SPIDY CRYPTO is a high-performance local trading assistant designed to monitor cryptocurrency markets on **Delta Exchange India**, detect high-probability institutional price action setups, enforce a **strict single-active-trade global lock**, dispatch automated **Telegram alerts**, persist audit history to **SQLite**, and render a **premium dark futuristic cyberpunk dashboard**.

---

## Key Features

1. **Delta Exchange India Integration**:
   - Live 5-minute (execution) and 15-minute (trend) candles via official REST (`https://api.india.delta.exchange`) and WebSocket (`wss://public-socket.india.delta.exchange`).
   - Stale-data guard, duplicate-candle filtering, and automatic REST fallback on disconnect.
2. **Markets Monitored**:
   - `ETHUSD`
   - `BTCUSD`
   - `SOLUSD`
3. **Pure Deterministic Strategy (No Direct LLM Trades)**:
   - Higher-Timeframe (15m) EMA Trend Bias.
   - 5m Fractal Swing Highs and Lows.
   - Clean Liquidity Sweeps (wick breaches swing extrema, closes back inside range).
   - Break of Structure (BOS) candle close confirmation.
   - Volume Confirmation (RVOL &ge; 1.15).
   - ATR-based dynamic stops and profit targets ($T_1 = 1.5R$, $T_2 = 2.5R$, $\text{RR} \ge 1.5$).
   - Deterministic 0–100 Setup Quality Score (minimum threshold: 70/100).
4. **Global Single-Active-Trade Lock**:
   - `MAX_ACTIVE_TRADES = 1`.
   - Only ONE trade can be active across ETH, BTC, and SOL.
   - If ETHUSD is active, BTCUSD and SOLUSD entries are blocked (`BLOCKED BY ACTIVE TRADE`).
   - If multiple coins trigger simultaneously, the highest-ranked setup is selected, with transparent rejection logs stored for the others.
5. **Trade State Lifecycle Tracking**:
   - `WATCHING` &rarr; `SETUP FOUND` &rarr; `WAITING` &rarr; `ACTIVE` &rarr; `TARGET HIT` &rarr; `COMPLETED` / `STOPPED` / `CANCELLED`.
6. **Telegram Notifications & Anti-Spam**:
   - Clean formatted alerts using `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   - Deterministic setup IDs ensure identical setups are never re-sent.
   - Alert logs persisted in SQLite across restarts.
7. **Crash Recovery**:
   - Restores active trade state from SQLite upon restart.
8. **Futuristic Cyberpunk Web Dashboard**:
   - Real-time WebSocket HUD at `http://127.0.0.1:8800`.
   - Canvas candlestick visualizer with active trade overlays.

---

## Directory Architecture

```
spidy_crypto/
├── config/              # Central configuration & parameters
├── market_data/         # Delta India REST & WebSocket clients, feed manager
├── indicators/          # ATR, Volume RVOL, EMA trend indicators
├── structure/           # Swings, Liquidity Sweeps, Break of Structure (BOS)
├── strategy/            # Deterministic setup detector & 0-100 quality scoring
├── risk_engine/         # Dynamic invalidation stop loss & target calculator
├── trade_manager/       # Central Trade Manager with MAX_ACTIVE_TRADES = 1 lock
├── telegram/            # Async Telegram bot client & message formatters
├── storage/             # SQLite database for history, active trade, and alerts
├── ui/                  # Static CSS, JS client, and HTML dashboard
├── tests/               # Pytest suite covering all 14 gates + live Delta API
├── server.py            # FastAPI backend and WebSocket hub
└── main.py              # CLI launcher
```

---

## Running the Application

### 1. Launch Server
```powershell
python main.py
```
Open your browser at:
`http://127.0.0.1:8800`

### 2. Run Test Suite
```powershell
pytest tests/ -v
```
All 15 automated unit, integration, and live API tests will execute.
