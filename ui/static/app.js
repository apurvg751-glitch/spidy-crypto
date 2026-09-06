// SPIDY CRYPTO Reactive Client HUD Engine (Institutional Cyber-War-Room Edition)
let ws = null;
let currentSymbol = "ETHUSD";
let currentResolution = "5m";
let currentCandles = [];
let activeTrade = null;
let marketStates = {};
let coinAnalysisData = {};
let selectedModelId = "MODEL_10";
let userManuallySelectedSymbol = false;
let lastActiveTradeId = null;

// Audio Synthesizer State
let soundEnabled = localStorage.getItem("spidy_sound_enabled") !== "false";
let audioCtx = null;

function initAudio() {
    if (!audioCtx) {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) audioCtx = new AudioContext();
        } catch (e) {
            console.warn("Web Audio API not supported", e);
        }
    }
    if (audioCtx && audioCtx.state === "suspended") {
        audioCtx.resume();
    }
}

function playSynthesizerTone(freq, type, duration, gainLevel = 0.15) {
    if (!soundEnabled) return;
    try {
        initAudio();
        if (!audioCtx) return;
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(gainLevel, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch (e) {
        // quiet audio fallback
    }
}

const SoundFX = {
    radarPing: () => {
        playSynthesizerTone(880, "sine", 0.15, 0.08);
    },
    tradeEntry: () => {
        playSynthesizerTone(440, "triangle", 0.1, 0.15);
        setTimeout(() => playSynthesizerTone(660, "sine", 0.25, 0.2), 100);
    },
    targetHit: () => {
        playSynthesizerTone(587.33, "sine", 0.12, 0.2);
        setTimeout(() => playSynthesizerTone(880, "triangle", 0.3, 0.25), 120);
    },
    alertWarning: () => {
        playSynthesizerTone(330, "sawtooth", 0.25, 0.12);
    }
};

function getSymbolPrecision(sym) {
    if (sym === "XRPUSD") return 4;
    if (sym === "AVAXUSD") return 3;
    if (sym === "BTCUSD") return 1;
    return 2;
}

function formatPrice(sym, val) {
    if (val === null || val === undefined || isNaN(val)) return "--";
    return Number(val).toFixed(getSymbolPrecision(sym));
}

// Chart Crosshair Interaction State
let chartHoverState = {
    active: false,
    x: 0,
    y: 0,
    candleIndex: -1
};

document.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    fetchStatus();
    
    // Initial selection
    selectSymbol("ETHUSD");

    // Market card coin selector
    document.querySelectorAll(".market-card").forEach(card => {
        card.addEventListener("click", () => {
            const sym = card.dataset.symbol;
            if (sym) {
                userManuallySelectedSymbol = true;
                selectSymbol(sym);
                SoundFX.radarPing();
            }
        });
    });

    // Timeframe selector buttons
    document.querySelectorAll(".tf-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentResolution = btn.dataset.tf;
            document.getElementById("chart-symbol-label").textContent = `${currentSymbol} • ${currentResolution.toUpperCase()} CHART`;
            loadCandles(currentSymbol, currentResolution);
            SoundFX.radarPing();
        });
    });

    // Audio pill toggle
    const audioPill = document.getElementById("audio-pill");
    if (audioPill) {
        updateAudioBadge();
        audioPill.addEventListener("click", () => {
            soundEnabled = !soundEnabled;
            localStorage.setItem("spidy_sound_enabled", soundEnabled);
            updateAudioBadge();
            if (soundEnabled) SoundFX.radarPing();
        });
    }

    // Operational action buttons
    const btnPower = document.getElementById("btn-power-toggle");
    if (btnPower) btnPower.addEventListener("click", toggleBotPower);

    const btnScan = document.getElementById("btn-scan");
    if (btnScan) btnScan.addEventListener("click", triggerScan);

    const btnBacktest = document.getElementById("btn-backtest");
    if (btnBacktest) btnBacktest.addEventListener("click", runBacktest);

    const btnValidate = document.getElementById("btn-validate");
    if (btnValidate) btnValidate.addEventListener("click", runValidation);

    const btnLong = document.getElementById("btn-sim-long");
    if (btnLong) btnLong.addEventListener("click", () => simulateSetup("LONG"));

    const btnShort = document.getElementById("btn-sim-short");
    if (btnShort) btnShort.addEventListener("click", () => simulateSetup("SHORT"));

    const btnRelease = document.getElementById("btn-release-lock");
    if (btnRelease) btnRelease.addEventListener("click", releaseActiveTradeLock);

    // Dedicated War Room Action Buttons
    const btnWtBe = document.getElementById("btn-wt-be");
    if (btnWtBe) btnWtBe.addEventListener("click", triggerBreakeven);

    const btnWtPartial = document.getElementById("btn-wt-partial");
    if (btnWtPartial) btnWtPartial.addEventListener("click", triggerPartial);

    const btnWtClose = document.getElementById("btn-wt-close");
    if (btnWtClose) btnWtClose.addEventListener("click", releaseActiveTradeLock);

    const btnWtView = document.getElementById("btn-wt-view");
    if (btnWtView) btnWtView.addEventListener("click", () => {
        if (activeTrade && activeTrade.coin) {
            userManuallySelectedSymbol = false;
            selectSymbol(activeTrade.coin);
        }
    });

    const btnSnapActive = document.getElementById("btn-snap-active");
    if (btnSnapActive) btnSnapActive.addEventListener("click", () => {
        if (activeTrade && activeTrade.coin) {
            userManuallySelectedSymbol = false;
            selectSymbol(activeTrade.coin);
        }
    });

    // Mobile Quick Dock Listeners (Thumb-friendly operations)
    const dockBe = document.getElementById("dock-btn-be");
    if (dockBe) dockBe.addEventListener("click", triggerBreakeven);

    const dockPartial = document.getElementById("dock-btn-partial");
    if (dockPartial) dockPartial.addEventListener("click", triggerPartial);

    const dockClose = document.getElementById("dock-btn-close");
    if (dockClose) dockClose.addEventListener("click", releaseActiveTradeLock);

    const dockScan = document.getElementById("dock-btn-scan");
    if (dockScan) dockScan.addEventListener("click", triggerScan);

    const dockPin = document.getElementById("dock-btn-pin");
    if (dockPin) {
        dockPin.addEventListener("click", () => {
            const stored = getStoredPin();
            if (stored) {
                if (confirm("Admin PIN is currently UNLOCKED. Do you want to lock it now?")) {
                    setStoredPin("");
                }
            } else {
                openPinModal(() => alert("Admin unlocked."));
            }
        });
    }

    // PIN Security Pill click listener
    const secPill = document.getElementById("security-pill");
    if (secPill) {
        secPill.addEventListener("click", () => {
            const stored = getStoredPin();
            if (stored) {
                if (confirm("Admin controls are currently UNLOCKED. Do you want to lock them now?")) {
                    setStoredPin("");
                }
            } else {
                openPinModal(() => alert("Admin unlocked successfully."));
            }
        });
    }

    // PIN modal buttons & Enter key
    const btnPinSubmit = document.getElementById("btn-pin-submit");
    if (btnPinSubmit) btnPinSubmit.addEventListener("click", submitPinAuth);

    const btnPinCancel = document.getElementById("btn-pin-cancel");
    if (btnPinCancel) btnPinCancel.addEventListener("click", closePinModal);

    const pinInput = document.getElementById("pin-input");
    if (pinInput) {
        pinInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") submitPinAuth();
            if (e.key === "Escape") closePinModal();
        });
    }

    // Initialize security badge from storage
    updateSecurityBadge(!!getStoredPin());

    // Canvas Chart Crosshair & Touch Listeners
    initChartInteraction();

    // High-frequency status polling to sync HUD with Telegram
    setInterval(() => {
        fetchStatus();
    }, 2500);
});

function updateAudioBadge() {
    const icon = document.getElementById("audio-icon");
    const txt = document.getElementById("audio-status-text");
    if (icon && txt) {
        if (soundEnabled) {
            icon.textContent = "🔊";
            txt.textContent = "AUDIO: ON";
            txt.style.color = "var(--cyan-neon)";
        } else {
            icon.textContent = "🔇";
            txt.textContent = "AUDIO: MUTED";
            txt.style.color = "var(--text-muted)";
        }
    }
}

function selectSymbol(sym) {
    currentSymbol = sym;

    // 1. Instantly highlight active card
    document.querySelectorAll(".market-card").forEach(c => {
        c.classList.toggle("selected", c.dataset.symbol === sym);
    });

    // 2. Instantly update tactical panel header and labels
    const coinBadge = document.getElementById("trade-badge-coin");
    if (coinBadge) coinBadge.textContent = sym;

    const chartLabel = document.getElementById("chart-symbol-label");
    if (chartLabel) chartLabel.textContent = `${sym} • ${currentResolution.toUpperCase()} CHART`;

    // 3. Update price levels locally ONLY if there is an active trade on this coin
    if (activeTrade && activeTrade.coin === sym && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING")) {
        document.getElementById("val-entry").textContent = formatPrice(sym, activeTrade.entry);
        document.getElementById("val-stop").textContent = formatPrice(sym, activeTrade.stop_loss);
        document.getElementById("val-t1").textContent = formatPrice(sym, activeTrade.target_1);
        document.getElementById("val-t2").textContent = formatPrice(sym, activeTrade.target_2);
        document.getElementById("val-margin").textContent = `₹${Number(activeTrade.margin_used || 4200).toLocaleString('en-IN')} (6x Leverage)`;

        const dirBadge = document.getElementById("trade-direction-badge");
        if (dirBadge) {
            dirBadge.textContent = activeTrade.direction;
            dirBadge.className = `direction-badge ${activeTrade.direction}`;
        }
    } else {
        document.getElementById("val-entry").textContent = "--";
        document.getElementById("val-stop").textContent = "--";
        document.getElementById("val-t1").textContent = "--";
        document.getElementById("val-t2").textContent = "--";
        document.getElementById("val-margin").textContent = "Idle (₹4,200 Margin @ 6x)";

        const m = marketStates[sym];
        const dirBadge = document.getElementById("trade-direction-badge");
        if (dirBadge) {
            const isBull = (m && m.mtf_context && m.mtf_context.exec_context_15m === "Bullish");
            dirBadge.textContent = isBull ? "BULLISH BIAS" : "BEARISH BIAS";
            dirBadge.className = `direction-badge ${isBull ? 'LONG' : 'SHORT'}`;
        }
    }

    // 4. Fetch candles and full deep SMC server analysis
    loadCandles(sym, currentResolution);
    fetchCoinAnalysis(sym);

    // 5. Contextual banner if previewing another coin while active trade is running
    const activeNotice = document.getElementById("tactical-active-notice");
    if (activeNotice) {
        if (activeTrade && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING") && sym !== activeTrade.coin) {
            activeNotice.style.display = "flex";
            const cEl = document.getElementById("tactical-notice-coin");
            const dEl = document.getElementById("tactical-notice-dir");
            const vEl = document.getElementById("tactical-notice-viewing");
            if (cEl) cEl.textContent = activeTrade.coin;
            if (dEl) {
                dEl.textContent = `(${activeTrade.direction})`;
                dEl.style.color = activeTrade.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
            }
            if (vEl) vEl.textContent = sym;
        } else {
            activeNotice.style.display = "none";
        }
    }
}

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            document.getElementById("ws-status-dot").className = "status-dot green";
            document.getElementById("ws-status-text").textContent = "STREAM LIVE";
        };

        ws.onclose = () => {
            document.getElementById("ws-status-dot").className = "status-dot rose";
            document.getElementById("ws-status-text").textContent = "RECONNECTING";
            setTimeout(initWebSocket, 2000);
        };

        ws.onerror = () => {
            try { ws.close(); } catch(e) {}
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWsMessage(data);
            } catch (e) {
                console.error("WS parse error", e);
            }
        };
    } catch (e) {
        console.error("WebSocket init error", e);
        setTimeout(initWebSocket, 3000);
    }
}

function handleWsMessage(msg) {
    if (msg.type === "STATUS_UPDATE" || msg.type === "INITIAL_STATE") {
        updateHUD(msg.data);
    } else if (msg.type === "PRICE_TICK") {
        updatePrice(msg.symbol, msg.price);
    } else if (msg.type === "CANDLE_CLOSED" && msg.symbol === currentSymbol && msg.resolution === currentResolution) {
        loadCandles(currentSymbol, currentResolution);
    }
}

async function fetchStatus() {
    try {
        const res = await fetch("/api/status");
        if (res.ok) {
            const data = await res.json();
            updateHUD(data);
        }
    } catch (e) {
        // quiet fallback
    }
}

async function fetchCoinAnalysis(sym) {
    try {
        const res = await fetch(`/api/analysis/${sym}`);
        if (res.ok) {
            const data = await res.json();
            coinAnalysisData[sym] = data;
            renderTacticalPanel(data);
            pushRadarEventsFromAnalysis(data);
        }
    } catch (e) {
        console.error("Error fetching coin analysis", e);
    }
}

async function loadCandles(sym, resParam) {
    try {
        const res = await fetch(`/api/candles/${sym}?resolution=${resParam || currentResolution}&limit=40`);
        if (res.ok) {
            const data = await res.json();
            currentCandles = data.candles || [];
            drawChart();
        }
    } catch (e) {
        console.error("Error fetching candles", e);
    }
}

function updateHUD(data) {
    if (data.markets) {
        marketStates = data.markets;
        for (const [sym, m] of Object.entries(data.markets)) {
            updatePrice(sym, m.current_price, m.is_stale, m.connection_status);
            if (m.mtf_context) {
                const el4h = document.getElementById(`mtf-4h-${sym}`);
                const el1h = document.getElementById(`mtf-1h-${sym}`);
                const el15 = document.getElementById(`mtf-15m-${sym}`);
                const el5 = document.getElementById(`mtf-5m-${sym}`);
                if (el4h) el4h.textContent = `4H: ${m.mtf_context.macro_bias_4h}`;
                if (el1h) el1h.textContent = `1H: ${m.mtf_context.trend_1h}`;
                if (el15) el15.textContent = `15M: ${m.mtf_context.exec_context_15m}`;
                if (el5) el5.textContent = `5M: ${m.mtf_context.struct_5m}`;
            }
        }
    }

    if (data.reentry_status) {
        for (const [sym, rStat] of Object.entries(data.reentry_status)) {
            const cardMeta = document.getElementById(`reentry-meta-${sym}`);
            if (cardMeta) {
                const rem = rStat.cooldown_remaining_bars || 0;
                if (rStat.state === "POST_TRADE_COOLDOWN" || rem > 0) {
                    cardMeta.innerHTML = `<span style="color:var(--amber-neon);">COOLDOWN (${rem} BARS)</span> | <span style="color:#ff3b5c;">BLOCKED</span>`;
                } else if (rStat.state === "WAITING_FOR_NEW_STRUCTURE") {
                    cardMeta.innerHTML = `<span style="color:var(--cyan-neon);">WAITING STRUCTURE</span> | <span style="color:#ff3b5c;">BLOCKED</span>`;
                } else {
                    cardMeta.innerHTML = `<span style="color:var(--emerald-neon);">READY</span> | <span style="color:var(--emerald-neon);">FRESH</span>`;
                }
            }

            if (sym === currentSymbol) {
                const stateEl = document.getElementById("reentry-state-badge");
                const cdEl = document.getElementById("reentry-cd-badge");
                const prevEl = document.getElementById("reentry-prev-setup");
                const structEl = document.getElementById("reentry-fresh-struct");
                const eligEl = document.getElementById("reentry-eligibility");

                if (stateEl) {
                    stateEl.textContent = rStat.state || "READY";
                    stateEl.style.color = (rStat.state === "POST_TRADE_COOLDOWN" || rStat.state === "WAITING_FOR_NEW_STRUCTURE") ? "var(--amber-neon)" : "var(--emerald-neon)";
                }
                if (cdEl) cdEl.textContent = `${rStat.cooldown_remaining_bars || 0} BARS`;
                if (prevEl) prevEl.textContent = rStat.previous_setup_status || "CONSUMED";
                if (structEl) {
                    structEl.textContent = rStat.fresh_structure || "CONFIRMED";
                    structEl.style.color = (rStat.fresh_structure === "NOT YET") ? "#ff3b5c" : "var(--emerald-neon)";
                }
                if (eligEl) {
                    eligEl.textContent = rStat.trade_eligibility || "READY";
                    eligEl.style.color = (rStat.trade_eligibility === "BLOCKED") ? "#ff3b5c" : "var(--emerald-neon)";
                }
            }
        }
    }

    activeTrade = data.active_trade;
    const lockDot = document.getElementById("lock-status-dot");
    const lockText = document.getElementById("lock-status-text");
    const standbyDot = document.getElementById("standby-dot");
    const standbyTitle = document.getElementById("standby-title");
    const standbyDesc = document.getElementById("standby-desc");
    const powerBtn = document.getElementById("btn-power-toggle");

    const isPaused = data.is_paused || data.global_status === "STOPPED";

    if (isPaused) {
        if (lockDot) lockDot.className = "status-dot red";
        if (lockText) lockText.textContent = "BOT STOPPED / PAUSED";

        if (standbyDot) standbyDot.className = "status-dot red";
        if (standbyTitle) {
            standbyTitle.textContent = "SPIDY BOT POWERED OFF / STOPPED";
            standbyTitle.style.color = "var(--rose-neon)";
        }
        if (standbyDesc) {
            standbyDesc.textContent = "Trading is paused. Bot will not enter any trades. Send /resume on Telegram or click Resume below.";
        }
        if (powerBtn) {
            powerBtn.textContent = "▶️ Power On / Resume Spidy Bot";
            powerBtn.style.borderColor = "var(--emerald-neon)";
            powerBtn.style.color = "var(--emerald-neon)";
        }
    } else if (activeTrade && (activeTrade.trade_status === "WAITING" || activeTrade.trade_status === "ACTIVE")) {
        if (lockDot) lockDot.className = "status-dot amber";
        if (lockText) lockText.textContent = `LOCKED (${activeTrade.coin})`;
        if (powerBtn) {
            powerBtn.textContent = "🛑 Power Off / Pause Spidy Bot";
            powerBtn.style.borderColor = "var(--rose-neon)";
            powerBtn.style.color = "var(--rose-neon)";
        }
    } else {
        if (lockDot) lockDot.className = "status-dot green";
        if (lockText) lockText.textContent = "SLOT OPEN (0/1)";
        if (standbyDot) standbyDot.className = "status-dot green";
        if (standbyTitle) {
            standbyTitle.textContent = "GLOBAL SLOT OPEN (0/1)";
            standbyTitle.style.color = "var(--emerald-neon)";
        }
        if (standbyDesc) {
            standbyDesc.textContent = "24/7 Institutional Scanner Active Across 6 Delta Exchange India Markets";
        }
        if (powerBtn) {
            powerBtn.textContent = "🛑 Power Off / Pause Spidy Bot";
            powerBtn.style.borderColor = "var(--rose-neon)";
            powerBtn.style.color = "var(--rose-neon)";
        }
    }

    // Render Dedicated Active Trade War Room Banner
    renderActiveTradeWarRoom(activeTrade);

    // Refresh tactical panel for currently selected coin
    fetchCoinAnalysis(currentSymbol);

    if (data.model_stats) {
        renderModelStats(data.model_stats);
    }

    if (data.history) {
        renderHistoryTable(data.history);
    }
}

function updatePrice(symbol, price, isStale, connStatus) {
    const priceEl = document.getElementById(`price-${symbol}`);
    if (priceEl && price > 0) {
        if (symbol === "XRPUSD") {
            priceEl.textContent = price.toFixed(4);
        } else if (price >= 1000) {
            priceEl.textContent = price.toLocaleString('en-US', {minimumFractionDigits: 1, maximumFractionDigits: 2});
        } else {
            priceEl.textContent = price.toFixed(2);
        }
    }
    const statusEl = document.getElementById(`status-${symbol}`);
    if (statusEl) {
        if (isStale) {
            statusEl.textContent = "STALE DATA";
            statusEl.style.color = "var(--rose-neon)";
        } else if (activeTrade && activeTrade.coin === symbol && (activeTrade.trade_status === "ACTIVE" || activeTrade.trade_status === "WAITING")) {
            statusEl.textContent = `🚨 IN TRADE (${activeTrade.direction})`;
            statusEl.style.color = activeTrade.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
        } else {
            statusEl.textContent = "SCANNING";
            statusEl.style.color = "var(--emerald-neon)";
        }
    }
    if (activeTrade && activeTrade.coin === symbol) {
        renderActiveTradeWarRoom(activeTrade);
    }
    if (symbol === currentSymbol) {
        const liveMarkEl = document.getElementById("chart-live-mark-hud");
        if (liveMarkEl) liveMarkEl.textContent = `LIVE MARK: $${formatPrice(symbol, price)}`;
        drawChart();
    }
}

function renderTacticalPanel(data) {
    if (!data || data.error) return;

    const sym = data.symbol;
    document.getElementById("trade-badge-coin").textContent = sym;

    const modeEl = document.getElementById("trade-coin-mode");
    if (data.is_active_trade) {
        modeEl.textContent = "LOCKED ACTIVE TRADE";
        modeEl.style.color = "var(--amber-neon)";
        modeEl.style.borderColor = "var(--amber-neon)";
        modeEl.style.background = "rgba(245, 158, 11, 0.15)";
    } else {
        modeEl.textContent = "LIVE COIN ANALYSIS";
        modeEl.style.color = "var(--cyan-neon)";
        modeEl.style.borderColor = "var(--cyan-neon)";
        modeEl.style.background = "rgba(0, 240, 255, 0.15)";
    }

    // Direction & Status
    const dirEl = document.getElementById("trade-direction-badge");
    dirEl.textContent = data.direction;
    dirEl.className = `direction-badge ${data.direction}`;

    const stEl = document.getElementById("trade-status-badge");
    stEl.textContent = data.status;

    document.getElementById("trade-model-badge").textContent = data.model_name;

    // Confirmations & Score
    document.getElementById("conf-badge-pill").textContent = `CONFIRMATIONS: ${data.confirmations_count}/7`;
    document.getElementById("score-number").textContent = data.score;

    // Grade & Policy Badges
    const gradeBadge = document.getElementById("trade-grade-badge");
    if (gradeBadge) {
        const gr = data.grade || "A+";
        gradeBadge.textContent = gr === "A+" ? "🌟 GRADE: A+" : "⚡ GRADE: B+";
        gradeBadge.style.color = gr === "A+" ? "var(--emerald-neon)" : "var(--amber-neon)";
        gradeBadge.style.borderColor = gr === "A+" ? "rgba(0,255,163,0.4)" : "rgba(245,158,11,0.4)";
        gradeBadge.style.background = gr === "A+" ? "rgba(0,255,163,0.15)" : "rgba(245,158,11,0.15)";
    }

    const policyBadge = document.getElementById("trade-policy-badge");
    if (policyBadge) {
        policyBadge.textContent = data.policy || (data.grade === "B+" ? "Strict Risk (Tight SL / Quick 1.6R TP)" : "Institutional Conviction");
    }

    // Dealing Range (Premium vs Discount) & Displacement
    if (data.dealing_range) {
        const dr = data.dealing_range;
        const rangeEl = document.getElementById("val-range-span");
        if (rangeEl) rangeEl.textContent = `[${dr.range_low.toFixed(1)} - ${dr.range_high.toFixed(1)}]`;

        const eqEl = document.getElementById("val-eq-price");
        if (eqEl) eqEl.textContent = dr.equilibrium.toFixed(1);

        const pdEl = document.getElementById("val-pd-zone");
        if (pdEl) {
            pdEl.textContent = `${dr.zone} (${(dr.current_position_pct * 100).toFixed(0)}%)`;
            pdEl.style.color = dr.zone.includes("DISCOUNT") ? "var(--emerald-neon)" : (dr.zone.includes("PREMIUM") ? "var(--rose-neon)" : "var(--cyan-neon)");
        }
    }

    if (data.displacement) {
        const dispEl = document.getElementById("val-displacement");
        if (dispEl) {
            dispEl.textContent = data.displacement.detected ? `DETECTED (${(data.displacement.body_ratio * 100).toFixed(0)}% body, ${data.displacement.expansion_ratio}x)` : "Normal";
            dispEl.style.color = data.displacement.detected ? "var(--emerald-neon)" : "var(--text-muted)";
        }
    }

    // Dynamic Levels tailored to this coin: ONLY when active trade is open!
    if (data.is_active_trade && data.levels) {
        document.getElementById("val-entry").textContent = formatPrice(sym, data.levels.entry);
        document.getElementById("val-stop").textContent = formatPrice(sym, data.levels.stop_loss);
        document.getElementById("val-t1").textContent = formatPrice(sym, data.levels.target_1);
        document.getElementById("val-t2").textContent = formatPrice(sym, data.levels.target_2);
        document.getElementById("val-margin").textContent = data.levels.margin || "₹4,200 Margin (6x Lev)";
    } else {
        document.getElementById("val-entry").textContent = "--";
        document.getElementById("val-stop").textContent = "--";
        document.getElementById("val-t1").textContent = "--";
        document.getElementById("val-t2").textContent = "--";
        document.getElementById("val-margin").textContent = "Idle (₹4,200 Margin @ 6x)";
    }

    // Delta Exchange India Point Value Telemetry
    const ptValEl = document.getElementById("val-point-value");
    if (ptValEl) {
        if (data.delta_telemetry) {
            const dt = data.delta_telemetry;
            const inrVal = Number(dt.point_value_inr || dt.inr_per_point || 0);
            ptValEl.textContent = `${dt.point_label} = ±₹${inrVal.toFixed(2)}`;
            ptValEl.title = `Delta Spec: ${dt.delta_contracts} ${dt.contract_unit} | Notional: ₹${Math.round(dt.notional_inr || 0).toLocaleString('en-IN')} ($${Math.round(dt.notional_usd || 0)})`;
        } else {
            ptValEl.textContent = "--";
        }
    }

    // Dynamic Progression Bar
    const progContainer = document.getElementById("progression-bar");
    if (progContainer && data.progression_steps) {
        progContainer.innerHTML = "";
        data.progression_steps.forEach((step, idx) => {
            const stepDiv = document.createElement("div");
            let cls = "prog-step";
            if (step.passed) {
                cls += " passed";
            } else if (idx === 0 || (data.progression_steps[idx - 1] && data.progression_steps[idx - 1].passed)) {
                cls += " active";
            }
            stepDiv.className = cls;
            stepDiv.textContent = step.label;
            stepDiv.title = step.desc || "";
            progContainer.appendChild(stepDiv);

            if (idx < data.progression_steps.length - 1) {
                const arrow = document.createElement("span");
                arrow.className = "prog-arrow";
                arrow.textContent = "▶";
                progContainer.appendChild(arrow);
            }
        });
    }

    // Setup Reasoning
    const reasonsContainer = document.getElementById("reasoning-container");
    reasonsContainer.innerHTML = "";
    if (data.reasons && Array.isArray(data.reasons)) {
        data.reasons.forEach(r => {
            const div = document.createElement("div");
            div.className = "reason-item";
            div.innerHTML = `<span class="highlight">▶</span> ${r}`;
            reasonsContainer.appendChild(div);
        });
    }

    drawChart();
}

// Institutional Radar Stream Events Queue
const radarEventsQueue = [];

function pushRadarEventsFromAnalysis(data) {
    if (!data) return;
    const container = document.getElementById("radar-feed-container");
    if (!container) return;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Look for high-priority radar events
    if (data.barrier && data.barrier.htf_institutional_walls && data.barrier.htf_institutional_walls.length > 0) {
        const wall = data.barrier.htf_institutional_walls[0];
        addRadarItem({
            sym: data.symbol,
            time: timeStr,
            desc: `1H/4H Institutional White Line Origin mapped at $${formatPrice(data.symbol, wall)}.`
        });
    }

    if (data.smt && data.smt.detected) {
        addRadarItem({
            sym: "SMT",
            time: timeStr,
            desc: `Intermarket SMT Divergence confirmed: ${data.smt.description}`
        });
    }

    if (data.kill_zone && data.kill_zone.is_active_kill_zone) {
        addRadarItem({
            sym: "SESSION",
            time: timeStr,
            desc: `Active Institutional Window: ${data.kill_zone.description}`
        });
    }
}

function addRadarItem(item) {
    // Avoid exact duplicate descriptions in queue
    if (radarEventsQueue.some(e => e.desc === item.desc && e.sym === item.sym)) return;

    radarEventsQueue.unshift(item);
    if (radarEventsQueue.length > 8) radarEventsQueue.pop();

    const container = document.getElementById("radar-feed-container");
    if (!container) return;

    container.innerHTML = "";
    radarEventsQueue.forEach(ev => {
        const card = document.createElement("div");
        card.className = "radar-event-card";
        card.innerHTML = `
            <div class="rec-top">
                <span class="rec-sym">${ev.sym}</span>
                <span class="rec-time">${ev.time}</span>
            </div>
            <div class="rec-desc">${ev.desc}</div>
        `;
        container.appendChild(card);
    });
}

function renderModelStats(stats) {
    const tbody = document.getElementById("model-stats-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    stats.forEach(s => {
        const tr = document.createElement("tr");
        const rColor = s.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
        tr.innerHTML = `
            <td style="font-weight:600; color:#fff;" title="${s.model_name}">${s.model_id}</td>
            <td>${s.trades_count}</td>
            <td style="color:${s.win_rate >= 50 ? 'var(--emerald-neon)' : 'var(--amber-neon)'}; font-weight:700;">${s.win_rate}%</td>
            <td style="color:${rColor}; font-weight:700;">${s.total_r > 0 ? '+' : ''}${s.total_r.toFixed(1)}R</td>
            <td>${s.profit_factor.toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderHistoryTable(items) {
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!items || items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; color:var(--text-muted);">No setups recorded yet.</td></tr>`;
        return;
    }

    items.slice(0, 35).forEach(item => {
        const tr = document.createElement("tr");
        const dt = new Date(item.detection_timestamp * 1000).toLocaleTimeString();

        let statusBadge = `<span style="color:var(--cyan-neon);">${item.trade_status}</span>`;
        if (item.trade_status === "BLOCKED BY ACTIVE TRADE") {
            statusBadge = `<span style="color:var(--amber-neon);">BLOCKED</span>`;
        } else if (item.trade_status === "COMPLETED" || item.trade_status === "TARGET HIT") {
            statusBadge = `<span style="color:var(--emerald-neon);">${item.trade_status}</span>`;
        } else if (item.trade_status === "STOPPED" || item.trade_status === "CANCELLED") {
            statusBadge = `<span style="color:var(--rose-neon);">${item.trade_status}</span>`;
        }

        const dirColor = item.direction === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
        const confText = item.confirmations_count ? `${item.confirmations_count}/7` : "-";

        tr.innerHTML = `
            <td>${dt}</td>
            <td style="font-weight:700; color:#fff;">${item.coin}</td>
            <td style="font-size:11px; color:var(--cyan-neon);">${item.model_id || 'M1'}</td>
            <td style="color:${dirColor}; font-weight:700;">${item.direction}</td>
            <td><strong style="color:var(--cyan-neon);">${item.setup_score}</strong>/100</td>
            <td style="color:var(--purple-neon); font-weight:700;">${confText}</td>
            <td>${item.entry ? formatPrice(item.coin, item.entry) : '-'}</td>
            <td>${item.stop_loss ? formatPrice(item.coin, item.stop_loss) : '-'}</td>
            <td>1:${item.rr ? item.rr.toFixed(1) : '-'}</td>
            <td>${statusBadge}</td>
            <td style="font-size:11px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${item.rejection_reason || item.final_result || ''}">
                ${item.rejection_reason || item.final_result || 'Qualified setup'}
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// ========================================================
// PRO-GRADE CANVAS CHART ENGINE (HTF WHITE LINE + SMC OVERLAYS)
// ========================================================
function initChartInteraction() {
    const canvas = document.getElementById("chart-canvas");
    if (!canvas) return;

    const handlePointerMove = (e) => {
        const rect = canvas.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        chartHoverState.active = true;
        chartHoverState.x = clientX - rect.left;
        chartHoverState.y = clientY - rect.top;
        drawChart();
    };

    const handlePointerLeave = () => {
        chartHoverState.active = false;
        const tip = document.getElementById("chart-tooltip");
        if (tip) tip.style.display = "none";
        drawChart();
    };

    canvas.addEventListener("mousemove", handlePointerMove);
    canvas.addEventListener("mouseleave", handlePointerLeave);
    canvas.addEventListener("touchmove", handlePointerMove, { passive: true });
    canvas.addEventListener("touchend", handlePointerLeave);
}

function drawChart() {
    const canvas = document.getElementById("chart-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;

    canvas.width = rect.width * window.devicePixelRatio;
    canvas.height = rect.height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

    const w = rect.width;
    const h = rect.height;

    ctx.clearRect(0, 0, w, h);

    if (!currentCandles || currentCandles.length === 0) {
        ctx.fillStyle = "rgba(255,255,255,0.25)";
        ctx.font = "12px monospace";
        ctx.textAlign = "center";
        ctx.fillText(`Loading ${currentSymbol} ${currentResolution.toUpperCase()} institutional telemetry...`, w / 2, h / 2);
        return;
    }

    const candles = currentCandles.slice(-40);
    const n = candles.length;
    let minPrice = Math.min(...candles.map(c => c.low));
    let maxPrice = Math.max(...candles.map(c => c.high));

    const coinData = coinAnalysisData[currentSymbol];
    
    // Include active trade levels in price scaling
    if (coinData && coinData.levels && coinData.is_active_trade) {
        minPrice = Math.min(minPrice, coinData.levels.stop_loss, coinData.levels.entry);
        maxPrice = Math.max(maxPrice, coinData.levels.target_2, coinData.levels.entry);
    }

    // Include HTF Institutional Walls ("The White Line") in bounds if near range
    const htfWalls = (coinData && coinData.barrier && coinData.barrier.htf_institutional_walls) || [];
    htfWalls.forEach(wall => {
        if (wall >= minPrice * 0.95 && wall <= maxPrice * 1.05) {
            minPrice = Math.min(minPrice, wall);
            maxPrice = Math.max(maxPrice, wall);
        }
    });

    // Include Dealing Range equilibrium
    if (coinData && coinData.dealing_range) {
        const dr = coinData.dealing_range;
        if (dr.range_low && dr.range_high) {
            minPrice = Math.min(minPrice, dr.range_low);
            maxPrice = Math.max(maxPrice, dr.range_high);
        }
    }

    const pad = (maxPrice - minPrice) * 0.12 || 1.0;
    minPrice -= pad;
    maxPrice += pad;
    const priceRange = maxPrice - minPrice;

    function getY(p) {
        return h - ((p - minPrice) / priceRange) * (h - 50) - 25;
    }

    // 1. DEALING RANGE ZONES (Premium vs Discount Tint)
    if (coinData && coinData.dealing_range) {
        const dr = coinData.dealing_range;
        const yEq = getY(dr.equilibrium);
        const yHigh = getY(dr.range_high);
        const yLow = getY(dr.range_low);

        // Premium Zone Fill (>50% Eq)
        ctx.fillStyle = "rgba(244, 63, 94, 0.04)";
        ctx.fillRect(40, Math.min(yHigh, yEq), w - 80, Math.abs(yHigh - yEq));

        // Discount Zone Fill (<50% Eq)
        ctx.fillStyle = "rgba(16, 185, 129, 0.04)";
        ctx.fillRect(40, Math.min(yEq, yLow), w - 80, Math.abs(yEq - yLow));

        // Equilibrium Dotted Line
        ctx.strokeStyle = "rgba(0, 240, 255, 0.4)";
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(40, yEq);
        ctx.lineTo(w - 40, yEq);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = "rgba(0, 240, 255, 0.7)";
        ctx.font = "9px monospace";
        ctx.textAlign = "right";
        ctx.fillText(`EQ 50%: ${formatPrice(currentSymbol, dr.equilibrium)}`, w - 45, yEq - 3);
    }

    // 2. BACKGROUND VOLATILITY GRID
    ctx.strokeStyle = "rgba(255, 255, 255, 0.04)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 5; i++) {
        const y = (h / 6) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    // 3. HTF INSTITUTIONAL WALLS ("THE WHITE LINE")
    htfWalls.forEach((wallPrice, idx) => {
        const yWall = getY(wallPrice);
        if (yWall >= 10 && yWall <= h - 10) {
            ctx.save();
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 1.8;
            ctx.setLineDash([8, 4]);
            ctx.shadowColor = "#ffffff";
            ctx.shadowBlur = 6;
            ctx.beginPath();
            ctx.moveTo(40, yWall);
            ctx.lineTo(w - 40, yWall);
            ctx.stroke();
            ctx.restore();

            // Luminous White Line label
            ctx.fillStyle = "#ffffff";
            ctx.font = "bold 9px monospace";
            ctx.textAlign = "left";
            ctx.fillText(`⚪ HTF WHITE LINE: $${formatPrice(currentSymbol, wallPrice)}`, 45, yWall - 4);
        }
    });

    // 4. CANDLESTICK RENDERING
    const chartLeft = 45;
    const chartRight = w - 45;
    const candleSpacing = (chartRight - chartLeft) / n;
    const candleWidth = Math.max(3.5, candleSpacing * 0.65);

    let hoveredCandle = null;
    let hoveredX = 0;
    let hoveredY = 0;

    candles.forEach((c, idx) => {
        const x = chartLeft + (idx + 0.5) * candleSpacing;
        const yOpen = getY(c.open);
        const yClose = getY(c.close);
        const yHigh = getY(c.high);
        const yLow = getY(c.low);

        const isGreen = c.close >= c.open;
        const color = isGreen ? "#10b981" : "#f43f5e";

        // Wick
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(x, yHigh);
        ctx.lineTo(x, yLow);
        ctx.stroke();

        // Candle Body
        ctx.fillStyle = color;
        const bodyTop = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(2, Math.abs(yOpen - yClose));
        ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyHeight);

        // Check hover
        if (chartHoverState.active && Math.abs(chartHoverState.x - x) < candleSpacing / 2) {
            hoveredCandle = c;
            hoveredX = x;
            hoveredY = chartHoverState.y;
        }
    });

    // 5. TECHNICAL LEVEL OVERLAYS (ONLY IF ACTIVE TRADE IS ON COIN)
    if (coinData && coinData.levels && coinData.is_active_trade) {
        const lvls = coinData.levels;
        drawHLine(ctx, w, getY(lvls.entry), "#00f0ff", `ENTRY: $${formatPrice(currentSymbol, lvls.entry)}`);
        drawHLine(ctx, w, getY(lvls.stop_loss), "#f43f5e", `STOP: $${formatPrice(currentSymbol, lvls.stop_loss)}`);
        drawHLine(ctx, w, getY(lvls.target_1), "#10b981", `TP1 (1.8R): $${formatPrice(currentSymbol, lvls.target_1)}`);
        drawHLine(ctx, w, getY(lvls.target_2), "#34d399", `TP2 (2.5R): $${formatPrice(currentSymbol, lvls.target_2)}`);
    }

    // 6. LIVE MARK BEACON
    const livePrice = (marketStates[currentSymbol] && marketStates[currentSymbol].current_price) ? marketStates[currentSymbol].current_price : (candles[candles.length - 1].close);
    if (livePrice) {
        const yLive = getY(livePrice);
        ctx.strokeStyle = "rgba(0, 240, 255, 0.75)";
        ctx.setLineDash([2, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chartLeft, yLive);
        ctx.lineTo(chartRight, yLive);
        ctx.stroke();
        ctx.setLineDash([]);

        // Live dot on right
        ctx.fillStyle = "#00f0ff";
        ctx.beginPath();
        ctx.arc(chartRight, yLive, 3.5, 0, Math.PI * 2);
        ctx.fill();
    }

    // 7. INTERACTIVE CROSSHAIR & TOOLTIP
    if (chartHoverState.active && hoveredCandle) {
        // Vertical crosshair
        ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hoveredX, 10);
        ctx.lineTo(hoveredX, h - 20);
        ctx.stroke();

        // Horizontal crosshair
        ctx.beginPath();
        ctx.moveTo(chartLeft, hoveredY);
        ctx.lineTo(chartRight, hoveredY);
        ctx.stroke();
        ctx.setLineDash([]);

        // Update Tooltip
        const tip = document.getElementById("chart-tooltip");
        if (tip) {
            tip.style.display = "block";
            tip.style.left = `${Math.min(w - 180, Math.max(10, hoveredX - 70))}px`;
            tip.style.top = `15px`;

            const c = hoveredCandle;
            const dt = c.time ? new Date(c.time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--';
            tip.innerHTML = `
                <div style="font-weight:800; color:var(--cyan-neon); margin-bottom:2px;">${currentSymbol} • ${dt}</div>
                <div>O: $${formatPrice(currentSymbol, c.open)} | H: $${formatPrice(currentSymbol, c.high)}</div>
                <div>L: $${formatPrice(currentSymbol, c.low)} | C: $${formatPrice(currentSymbol, c.close)}</div>
            `;
        }
    }
}

function drawHLine(ctx, w, y, color, label) {
    ctx.strokeStyle = color;
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(40, y);
    ctx.lineTo(w - 40, y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw pill tag
    ctx.fillStyle = color;
    ctx.font = "bold 9px monospace";
    ctx.textAlign = "right";
    ctx.fillText(label, w - 45, y - 4);
}

// ==========================================
// WAR ROOM RENDERING & JOURNEY TRACK
// ==========================================
function renderActiveTradeWarRoom(at) {
    const banner = document.getElementById("global-active-trade-banner");
    const standby = document.getElementById("global-standby-banner");
    if (!banner || !standby) return;

    if (!at || (at.trade_status !== "ACTIVE" && at.trade_status !== "WAITING")) {
        banner.style.display = "none";
        standby.style.display = "flex";
        const activeNotice = document.getElementById("tactical-active-notice");
        if (activeNotice) activeNotice.style.display = "none";
        document.querySelectorAll(".market-card").forEach(c => {
            c.classList.remove("in-trade");
            const sym = c.dataset.symbol;
            const stEl = document.getElementById(`status-${sym}`);
            if (stEl) {
                stEl.textContent = "SCANNING";
                stEl.style.color = "var(--emerald-neon)";
            }
        });
        return;
    }

    // Active trade is LIVE!
    banner.style.display = "flex";
    standby.style.display = "none";

    const sym = at.coin;
    const dir = (at.direction || "LONG").toUpperCase();
    const entry = Number(at.entry || 0);
    const sl = Number(at.stop_loss || 0);
    const t1 = Number(at.target_1 || 0);
    const t2 = Number(at.target_2 || 0);
    const margin = Number(at.margin_used || 4200);
    const lev = Number(at.leverage || 6);

    // Header badge group
    const dirBadge = document.getElementById("wt-coin-dir");
    if (dirBadge) {
        dirBadge.textContent = `${sym} ${dir}`;
        dirBadge.className = `war-room-dir-badge ${dir}`;
    }

    const gradeEl = document.getElementById("wt-grade");
    if (gradeEl) gradeEl.textContent = `GRADE: ${at.grade || 'A+'}`;

    const scoreEl = document.getElementById("wt-score");
    if (scoreEl) scoreEl.textContent = `SCORE: ${at.setup_score || 85}/100`;

    const modelEl = document.getElementById("wt-model");
    if (modelEl) modelEl.textContent = at.model_name || "Institutional Strategy";

    // Levels
    const entryEl = document.getElementById("wt-entry");
    if (entryEl) entryEl.textContent = `$${formatPrice(sym, entry)}`;

    const stopEl = document.getElementById("wt-stop");
    if (stopEl) stopEl.textContent = `$${formatPrice(sym, sl)}`;

    const t1El = document.getElementById("wt-t1");
    if (t1El) t1El.textContent = `$${formatPrice(sym, t1)}`;

    const t2El = document.getElementById("wt-t2");
    if (t2El) t2El.textContent = `$${formatPrice(sym, t2)}`;

    const marginEl = document.getElementById("wt-margin");
    if (marginEl) marginEl.textContent = `₹${margin.toLocaleString('en-IN')} (${lev}x)`;

    // Delta Contract Specs & Point Values
    const pointValEl = document.getElementById("wt-point-val");
    const deltaContractsEl = document.getElementById("wt-delta-contracts");
    const pointsMovedEl = document.getElementById("wt-points-moved");

    let ptInr = Number(at.point_val_inr || 0);
    let ptLabel = at.point_label || "1.0 pt";
    let contracts = (at.delta_contracts !== undefined && at.delta_contracts !== null) ? at.delta_contracts : (at.units || "--");
    let cUnit = at.contract_unit || "Lots";

    if (pointValEl) {
        pointValEl.textContent = ptInr > 0 ? `${ptLabel} = ±₹${ptInr.toFixed(2)}` : "--";
    }
    if (deltaContractsEl) {
        deltaContractsEl.textContent = `${contracts} ${cUnit}`;
    }

    // Live Mark & Real-time Dynamic PnL calculation
    let liveP = (marketStates[sym] && marketStates[sym].current_price) ? Number(marketStates[sym].current_price) : (Number(at.current_price) || entry);
    const markEl = document.getElementById("wt-mark");
    if (markEl) markEl.textContent = `$${formatPrice(sym, liveP)}`;

    let priceDiff = dir === "LONG" ? (liveP - entry) : (entry - liveP);
    let pointsMoved = priceDiff;
    let ptsSign = pointsMoved >= 0 ? "+" : "";
    let ptsFormatted = sym === "XRPUSD" ? pointsMoved.toFixed(4) : (Math.abs(pointsMoved) >= 100 ? pointsMoved.toFixed(1) : pointsMoved.toFixed(2));

    if (pointsMovedEl) {
        pointsMovedEl.textContent = `${ptsSign}${ptsFormatted} pts`;
        pointsMovedEl.style.color = pointsMoved >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
    }

    let pnlInr = ptInr > 0 ? (pointsMoved * ptInr) : (margin * ((entry > 0 ? priceDiff / entry : 0) * lev));
    let pnlPct = margin > 0 ? (pnlInr / margin) * 100 : 0;
    let riskDist = Math.abs(entry - sl);
    let achR = riskDist > 0 ? (priceDiff / riskDist) : 0;

    let pnlSign = pnlInr >= 0 ? "+" : "";
    let pnlColor = pnlInr >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";

    const pnlEl = document.getElementById("wt-pnl");
    if (pnlEl) {
        pnlEl.textContent = `${pnlSign}₹${pnlInr.toFixed(2)} (${pnlSign}${pnlPct.toFixed(2)}%)`;
        pnlEl.style.color = pnlColor;
    }

    const rEl = document.getElementById("wt-r");
    if (rEl) {
        rEl.textContent = `${pnlSign}${achR.toFixed(2)}R`;
        rEl.style.color = pnlColor;
    }

    // UPDATE TARGET CONVERGENCE JOURNEY TRACK
    const journeyBar = document.getElementById("wt-journey-bar");
    const journeyPointer = document.getElementById("wt-journey-pointer");
    const journeyPct = document.getElementById("wt-journey-pct");

    const jValEntry = document.getElementById("j-val-entry");
    const jValT1 = document.getElementById("j-val-t1");
    const jValT2 = document.getElementById("j-val-t2");

    if (jValEntry) jValEntry.textContent = `$${formatPrice(sym, entry)}`;
    if (jValT1) jValT1.textContent = `$${formatPrice(sym, t1)}`;
    if (jValT2) jValT2.textContent = `$${formatPrice(sym, t2)}`;

    // Calculate percentage toward TP1 (where 100% = TP1)
    let t1Dist = Math.abs(t1 - entry);
    let progressPct = t1Dist > 0 ? Math.max(0, Math.min(100, (priceDiff / t1Dist) * 100)) : 0;

    if (journeyBar) journeyBar.style.width = `${progressPct}%`;
    if (journeyPointer) journeyPointer.style.left = `${progressPct}%`;
    if (journeyPct) {
        journeyPct.textContent = `${progressPct.toFixed(1)}% TO TP1 (${pnlSign}${achR.toFixed(2)}R)`;
    }

    const stepBe = document.getElementById("j-step-be");
    const stepT1 = document.getElementById("j-step-t1");
    if (stepBe) {
        stepBe.className = achR >= 0.8 ? "journey-step passed" : "journey-step";
    }
    if (stepT1) {
        stepT1.className = achR >= 1.6 ? "journey-step passed" : "journey-step";
    }

    // Highlight card in market strip
    document.querySelectorAll(".market-card").forEach(c => {
        const cardSym = c.dataset.symbol;
        const stEl = document.getElementById(`status-${cardSym}`);
        if (cardSym === sym) {
            c.classList.add("in-trade");
            if (stEl) {
                stEl.textContent = `🚨 IN TRADE (${dir})`;
                stEl.style.color = dir === "LONG" ? "var(--emerald-neon)" : "var(--rose-neon)";
            }
        } else {
            c.classList.remove("in-trade");
            if (stEl) {
                stEl.textContent = "SCANNING";
                stEl.style.color = "var(--emerald-neon)";
            }
        }
    });

    // Auto-focus on active trade coin if a new trade was opened
    if (at.setup_id && at.setup_id !== lastActiveTradeId) {
        lastActiveTradeId = at.setup_id;
        userManuallySelectedSymbol = false;
        selectSymbol(sym);
        SoundFX.tradeEntry();
    } else if (!userManuallySelectedSymbol && currentSymbol !== sym) {
        selectSymbol(sym);
    }
}

// ==========================================
// 4-DIGIT ADMIN PIN SECURITY SYSTEM (PIN: 1408)
// ==========================================
let pendingPinAction = null;

function getStoredPin() {
    return sessionStorage.getItem("spidy_admin_pin") || localStorage.getItem("spidy_admin_pin") || "";
}

function setStoredPin(pin) {
    if (pin) {
        sessionStorage.setItem("spidy_admin_pin", pin);
        localStorage.setItem("spidy_admin_pin", pin);
        updateSecurityBadge(true);
    } else {
        sessionStorage.removeItem("spidy_admin_pin");
        localStorage.removeItem("spidy_admin_pin");
        updateSecurityBadge(false);
    }
}

function updateSecurityBadge(unlocked) {
    const icon = document.getElementById("security-lock-icon");
    const txt = document.getElementById("security-status-text");
    if (icon && txt) {
        if (unlocked) {
            icon.textContent = "🔓";
            txt.textContent = "ADMIN UNLOCKED";
            txt.style.color = "var(--emerald-neon)";
        } else {
            icon.textContent = "🔒";
            txt.textContent = "PIN LOCKED";
            txt.style.color = "var(--amber-neon)";
        }
    }
}

async function verifyPinWithServer(pin) {
    try {
        const res = await fetch("/api/verify_pin", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pin: pin })
        });
        return res.ok;
    } catch (e) {
        console.error("PIN verification error", e);
        return false;
    }
}

function openPinModal(onSuccess) {
    pendingPinAction = onSuccess;
    const modal = document.getElementById("pin-modal");
    const input = document.getElementById("pin-input");
    const errMsg = document.getElementById("pin-error-msg");
    if (modal && input) {
        modal.style.display = "flex";
        input.value = "";
        if (errMsg) errMsg.textContent = "";
        setTimeout(() => input.focus(), 50);
    }
}

function closePinModal() {
    const modal = document.getElementById("pin-modal");
    if (modal) modal.style.display = "none";
    pendingPinAction = null;
}

async function submitPinAuth() {
    const input = document.getElementById("pin-input");
    const errMsg = document.getElementById("pin-error-msg");
    const pin = (input ? input.value : "").trim();
    if (!pin) {
        if (errMsg) errMsg.textContent = "Please enter 4-digit PIN";
        return;
    }

    const isValid = await verifyPinWithServer(pin);
    if (isValid) {
        setStoredPin(pin);
        const action = pendingPinAction;
        closePinModal();
        SoundFX.radarPing();
        if (action) action(pin);
    } else {
        if (errMsg) errMsg.textContent = "❌ Invalid PIN. Access Denied.";
        SoundFX.alertWarning();
        if (input) {
            input.value = "";
            input.focus();
        }
    }
}

function requireAdminPin(action) {
    const stored = getStoredPin();
    if (stored) {
        action(stored);
    } else {
        openPinModal(action);
    }
}

async function releaseActiveTradeLock() {
    if (!confirm("Are you sure you want to command SPIDY to stop and close the active trade?")) {
        return;
    }
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/close_active_trade", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => releaseActiveTradeLock());
                return;
            }
            const data = await res.json();
            fetchStatus();
            fetchCoinAnalysis(currentSymbol);
            SoundFX.alertWarning();
            alert(data.message || "Active trade lock released.");
        } catch (e) {
            console.error("Release lock error", e);
        }
    });
}

let lastBacktestByMarket = null;

async function triggerScan() {
    const btn = document.getElementById("btn-scan");
    const box = document.getElementById("scan-result-box");
    const content = document.getElementById("scan-result-content");

    if (btn) {
        btn.disabled = true;
        btn.textContent = "⏳ Scanning 9 Models Across Markets...";
        btn.style.borderColor = "var(--amber-neon)";
        btn.style.color = "var(--amber-neon)";
    }
    if (box) {
        box.style.display = "block";
        content.innerHTML = "<em>Querying Delta Exchange live feeds & evaluating 27 model checks...</em>";
    }

    try {
        const res = await fetch("/api/trigger_scan", { method: "POST" });
        const data = await res.json();
        
        if (box && data.results) {
            let html = `<div style="margin-bottom:6px; color:#fff;">${data.message}</div>`;
            html += `<table style="width:100%; font-size:10px; border-collapse:collapse;">`;
            data.results.forEach(r => {
                html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.05); padding:2px 0;">
                    <td style="font-weight:700; color:var(--cyan-neon); padding:2px 4px;">${r.symbol}:</td>
                    <td style="color:${r.status.includes('QUALIFIED') ? 'var(--emerald-neon)' : 'var(--text-secondary)'}; padding:2px 4px;">${r.status}</td>
                    <td style="color:var(--purple-neon); padding:2px 4px;">${r.confirmations}</td>
                    <td style="color:var(--text-muted); padding:2px 4px;">${r.best_model}</td>
                </tr>`;
            });
            html += `</table>`;
            content.innerHTML = html;
        }

        SoundFX.radarPing();
        fetchStatus();
        fetchCoinAnalysis(currentSymbol);
    } catch (e) {
        if (content) content.textContent = "Scan error: " + e;
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "⚡ Trigger Market Scan (9 Models) ✓";
            btn.style.borderColor = "var(--cyan-neon)";
            btn.style.color = "#fff";
            setTimeout(() => {
                btn.textContent = "⚡ Trigger Market Scan (9 Models)";
            }, 2500);
        }
    }
}

async function runBacktest() {
    const box = document.getElementById("backtest-summary-box");
    const content = document.getElementById("backtest-summary-content");
    box.style.display = "block";
    content.innerHTML = `<em>Running event-driven institutional backtest for <strong>${currentSymbol}</strong> & portfolio...</em>`;

    try {
        const res = await fetch(`/api/backtest/run?symbol=${currentSymbol}`, { method: "POST" });
        const data = await res.json();
        if (data.metrics) {
            const m = data.metrics;
            lastBacktestByMarket = data.by_market;
            const rColor = m.total_r_gain >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";

            let html = `
                <div style="font-size:12px; margin-bottom:4px;">
                    <strong style="color:var(--cyan-neon);">[ ${data.selected_symbol} BACKTEST ]:</strong>
                    Trades: <strong>${m.total_trades}</strong> | 
                    Win Rate: <strong style="color:var(--emerald-neon)">${m.win_rate}%</strong> | 
                    Expectancy: <strong>${m.expectancy}R</strong> | 
                    Profit Factor: <strong>${m.profit_factor}</strong> | 
                    Total Gain: <strong style="color:${rColor}">${m.total_r_gain > 0 ? '+' : ''}${m.total_r_gain}R</strong> | 
                    Max DD: <strong>${m.max_drawdown_r}R</strong>
                </div>
            `;

            if (data.by_market && Object.keys(data.by_market).length > 0) {
                html += `<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:12px; font-size:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:6px;">`;
                for (const [sym, bm] of Object.entries(data.by_market)) {
                    const bmColor = bm.total_r >= 0 ? "var(--emerald-neon)" : "var(--rose-neon)";
                    const isSelected = sym === currentSymbol;
                    html += `
                        <div style="${isSelected ? 'background:rgba(0,240,255,0.15); padding:2px 6px; border-radius:4px; border:1px solid var(--cyan-neon);' : ''}">
                            <strong style="color:${isSelected ? 'var(--cyan-neon)' : '#fff'};">${sym}:</strong> 
                            ${bm.trades} trds | 
                            WR: <strong style="color:var(--emerald-neon);">${bm.win_rate}%</strong> | 
                            Gain: <strong style="color:${bmColor};">${bm.total_r > 0 ? '+' : ''}${bm.total_r}R</strong> | 
                            PF: ${bm.profit_factor}
                        </div>
                    `;
                }
                html += `</div>`;
            }

            content.innerHTML = html;
            SoundFX.radarPing();

            if (data.model_stats) {
                renderModelStats(data.model_stats);
            }
        }
    } catch (e) {
        content.textContent = "Error executing backtest: " + e;
    }
}

async function runValidation() {
    const box = document.getElementById("backtest-summary-box");
    const content = document.getElementById("backtest-summary-content");
    box.style.display = "block";
    content.innerHTML = `<em>Running In-Sample (70%) vs Out-of-Sample (30%) validation for <strong>${currentSymbol}</strong>...</em>`;

    try {
        const res = await fetch(`/api/backtest/validate?symbol=${currentSymbol}`, { method: "POST" });
        const data = await res.json();
        if (data.retention) {
            content.innerHTML = `
                <div style="font-size:12px; margin-bottom:4px;">
                    <strong style="color:var(--cyan-neon);">[ ${data.selected_symbol} VALIDATION ]:</strong>
                    In-Sample Trades: <strong>${data.in_sample_trades}</strong> (WR: <strong style="color:var(--emerald-neon);">${data.in_sample_metrics.win_rate}%</strong>)<br>
                    Out-of-Sample Trades: <strong>${data.out_of_sample_trades}</strong> (WR: <strong style="color:var(--emerald-neon);">${data.out_of_sample_metrics.win_rate}%</strong>)<br>
                    Win Rate Retention: <strong>${data.retention.win_rate_retention_pct}%</strong> | 
                    Robust Institutional Edge: <strong style="color:${data.is_robust ? 'var(--emerald-neon)' : 'var(--amber-neon)'}">${data.is_robust ? 'CONFIRMED' : 'REFINING'}</strong>
                </div>
            `;
            SoundFX.radarPing();
        }
    } catch (e) {
        content.textContent = "Error executing validation: " + e;
    }
}

async function simulateSetup(dir) {
    requireAdminPin(async (pin) => {
        try {
            const modelEl = document.getElementById("select-test-model");
            const modelId = modelEl ? modelEl.value : "MODEL_10";
            const res = await fetch(`/api/simulate_setup?symbol=${currentSymbol}&direction=${dir}&model_id=${modelId}&force=true`, {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => simulateSetup(dir));
                return;
            }
            await res.json();
            SoundFX.tradeEntry();
            fetchStatus();
            fetchCoinAnalysis(currentSymbol);
        } catch (e) {
            console.error("Simulation error", e);
        }
    });
}

async function triggerBreakeven() {
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/breakeven", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => triggerBreakeven());
                return;
            }
            const data = await res.json();
            SoundFX.targetHit();
            alert(data.message || "Breakeven applied.");
            fetchStatus();
        } catch (e) {
            console.error("Breakeven error", e);
        }
    });
}

async function triggerPartial() {
    requireAdminPin(async (pin) => {
        try {
            const res = await fetch("/api/partial", {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => triggerPartial());
                return;
            }
            const data = await res.json();
            SoundFX.targetHit();
            alert(data.message || "Partial profit secured.");
            fetchStatus();
        } catch (e) {
            console.error("Partial error", e);
        }
    });
}

async function toggleBotPower() {
    const powerBtn = document.getElementById("btn-power-toggle");
    const isPaused = powerBtn && powerBtn.textContent.includes("Resume");
    const endpoint = isPaused ? "/api/resume" : "/api/pause";
    requireAdminPin(async (pin) => {
        try {
            if (powerBtn) powerBtn.disabled = true;
            const res = await fetch(endpoint, {
                method: "POST",
                headers: { "X-Admin-PIN": pin }
            });
            if (res.status === 401) {
                setStoredPin("");
                alert("❌ Unauthorized: Invalid Admin PIN. Please authenticate.");
                openPinModal(() => toggleBotPower());
                return;
            }
            const data = await res.json();
            SoundFX.alertWarning();
            alert(data.message || "State updated.");
            await fetchStatus();
        } catch (e) {
            console.error("Power toggle error", e);
        } finally {
            if (powerBtn) powerBtn.disabled = false;
        }
    });
}
